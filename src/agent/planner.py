"""The real Planner: one propose_action model call per turn.

Week 8, Member 3. ``PromptPlanner`` satisfies the ``Planner`` protocol in
``agent.loop``. Each turn it sends the current propose_action prompt
(``prompts.loader.load_latest``) as the system prompt and a user message made
of the goal, the context text from the sensor, an optional memory block, and
the guarded observation history, then parses the reply with
``ProposalSet.model_validate_json`` (the existing parser in ``models.types``).
Citations are not checked here: the loop calls
``orchestrator.validation.validate_citations`` on every proposal, and a
rejection there is an observation the loop may retry, not a planner failure.

Failures. Every failure raises ``PlannerError`` with a ``PlannerFailure``
kind; the loop turns any planner exception into ``LoopFailure.PLAN_FAILED``
and never keeps its text. The kind is also kept on ``last_failure``. The
error is raised outside the ``except`` block, so neither its message nor its
``__context__`` carries the client's exception text or anything in it.

Truncation. The model client does not report why generation stopped, so a
reply cut short by the token limit is indistinguishable from a malformed one
and is reported as ``MALFORMED_REPLY``.

The client, temperature, token limit and timeout come from the caller's
client; ``from_config`` builds it with ``config.build_model_client``, which
reads the environment. Nothing here names a model, key or endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from models.client import (
    ModelAuthenticationError,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
)
from models.types import ProposalSet
from prompts.loader import PromptVersion, load_latest
from rag.context_builder import AssembledContext
from rag.injection_flagging import flag_trace_entry

from .history_guard import DEFAULT_HISTORY_CHAR_BUDGET, render_history
from .loop import AgentTask, LoopState, TraceSink

PROMPT_ID = "propose_action"


class PlannerFailure(str, Enum):
    MALFORMED_REPLY = "malformed_reply"
    EMPTY_REPLY = "empty_reply"
    CLIENT_ERROR = "client_error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION = "authentication"


_MESSAGES = {
    PlannerFailure.MALFORMED_REPLY: "The model reply could not be parsed as a proposal.",
    PlannerFailure.EMPTY_REPLY: "The model returned an empty reply.",
    PlannerFailure.CLIENT_ERROR: "The model call failed.",
    PlannerFailure.TIMEOUT: "The model call timed out.",
    PlannerFailure.RATE_LIMITED: "The model provider refused the call because of a rate limit.",
    PlannerFailure.AUTHENTICATION: "The model provider rejected the configured credentials.",
}


class PlannerError(Exception):
    """A planning failure with a fixed message. Never carries provider text."""

    def __init__(self, kind: PlannerFailure) -> None:
        super().__init__(_MESSAGES[kind])
        self.kind = kind


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _classify(exc: Exception) -> PlannerFailure:
    if isinstance(exc, ModelTimeoutError):
        return PlannerFailure.TIMEOUT
    if isinstance(exc, ModelRateLimitError):
        return PlannerFailure.RATE_LIMITED
    if isinstance(exc, ModelAuthenticationError):
        return PlannerFailure.AUTHENTICATION
    return PlannerFailure.CLIENT_ERROR


class PromptPlanner:
    """Planner that makes one propose_action call per turn."""

    def __init__(
        self,
        client: Any,
        *,
        prompt: PromptVersion | None = None,
        trace_sink: TraceSink | None = None,
        clock: Callable[[], datetime] = _utc_now,
        memory: Any = None,
        memory_module: str | None = None,
        memory_max_records: int = 20,
        memory_max_chars: int = 2_000,
        history_max_chars: int = DEFAULT_HISTORY_CHAR_BUDGET,
    ) -> None:
        if not hasattr(client, "generate"):
            raise ValueError("PromptPlanner needs a model client with generate().")
        if memory is not None and not (isinstance(memory_module, str) and memory_module.strip()):
            raise ValueError("A memory object needs the module whose memory to render.")
        self.client = client
        self.prompt = prompt if prompt is not None else load_latest(PROMPT_ID)
        self.trace_sink = trace_sink
        self.clock = clock
        self.memory = memory
        self.memory_module = memory_module
        self.memory_max_records = memory_max_records
        self.memory_max_chars = memory_max_chars
        self.history_max_chars = history_max_chars
        self.last_failure: PlannerFailure | None = None
        self.sink_failures = 0

    @classmethod
    def from_config(cls, **kwargs: Any) -> "PromptPlanner":
        """Build the planner with the client from ``config.build_model_client``."""

        from config import build_model_client

        return cls(build_model_client(), **kwargs)

    def build_user_content(
        self, task: AgentTask, context: AssembledContext, state: LoopState
    ) -> str:
        """The user message for one turn; also traces any history flags."""

        parts = [f"GOAL: {task.goal}", context.text]
        if self.memory is not None:
            parts.append(
                self.memory.render_for_prompt(
                    self.memory_module,
                    max_records=self.memory_max_records,
                    max_chars=self.memory_max_chars,
                )
            )
        if state.history:
            history_text, flagged = render_history(state.history, max_chars=self.history_max_chars)
            parts.append("OBSERVATION HISTORY:\n" + history_text)
            self._trace(task, flagged)
        return "\n\n".join(parts)

    def plan(self, task: AgentTask, context: AssembledContext, state: LoopState) -> ProposalSet:
        user_content = self.build_user_content(task, context, state)
        failure: PlannerFailure | None = None
        raw = ""
        try:
            raw = self.client.generate(system_prompt=self.prompt.text, user_content=user_content).raw_text
        except Exception as exc:
            failure = _classify(exc)
        if failure is None and (not isinstance(raw, str) or not raw.strip()):
            failure = PlannerFailure.EMPTY_REPLY
        proposal = None
        if failure is None:
            try:
                # A reply truncated by the token limit also lands here: the
                # client does not say why generation stopped.
                proposal = ProposalSet.model_validate_json(raw)
            except (ModelResponseError, TypeError, ValueError, KeyError, AttributeError):
                failure = PlannerFailure.MALFORMED_REPLY
        self.last_failure = failure
        if failure is not None:
            # Raised here, outside any except block, so no provider exception
            # is attached as __context__.
            raise PlannerError(failure)
        return proposal

    def _trace(self, task: AgentTask, flagged: tuple) -> None:
        if not flagged or self.trace_sink is None:
            return
        try:
            self.trace_sink.record(flag_trace_entry(task.context.session_id, flagged, self.clock()))
        except Exception:
            self.sink_failures += 1


__all__ = ["PlannerError", "PlannerFailure", "PromptPlanner"]
