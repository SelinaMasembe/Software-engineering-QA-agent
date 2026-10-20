"""Run one bounded sense -> plan -> validate -> act -> observe session.

This module is the Week 5 Member 2 agent loop. It connects contributions that
already exist rather than re-implementing them:

- sensing is injected and returns ``rag.AssembledContext`` (retrieval plus
  Member 3's context builder);
- planning is injected and returns one ``models.types.ProposalSet``
  (the propose_action model call);
- citations are checked with ``orchestrator.validation.validate_citations``
  before anything is dispatched;
- tools run only through ``orchestrator.ToolDispatcher`` and its approval gate;
- whether to continue is decided by Member 1's injected stop evaluator;
- trace entries go to Member 5's injected trace sink.

The loop does not parse Member 3's task contract, hard-code any stop policy,
or persist traces. Each turn plans at most one action and calls the
dispatcher at most once. Any failing dependency stops the loop with a fixed,
sanitized result instead of raw exception text.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from models.types import (
    Action,
    Actor,
    Confidence,
    EvidenceRef,
    LoopHaltEvent,
    ProposalSet,
    StopReason,
    ToolInvocation,
    TraceEntry,
    UntraceableProposalError,
)
from orchestrator import (
    TOOL_ACTIONS,
    DispatchCode,
    DispatchResult,
    DispatchStatus,
    ExecutionContext,
)
from orchestrator.validation import validate_citations
from rag import AssembledContext


class LoopStatus(str, Enum):
    """Explicit end state of one ``run`` or ``resume`` call."""

    COMPLETED = "completed"
    NO_ACTION = "no_action"
    AWAITING_APPROVAL = "awaiting_approval"
    HALTED = "halted"
    FAILED = "failed"


class LoopFailure(str, Enum):
    """Which injected component failed when the status is ``FAILED``."""

    SENSE_FAILED = "sense_failed"
    PLAN_FAILED = "plan_failed"
    VALIDATION_FAILED = "validation_failed"
    DISPATCH_FAILED = "dispatch_failed"
    STOP_CHECK_FAILED = "stop_check_failed"
    TRACE_FAILED = "trace_failed"


class ObservationKind(str, Enum):
    """What happened to the action planned in one non-final turn."""

    TOOL_EXECUTED = "tool_executed"
    TOOL_REJECTED = "tool_rejected"
    TOOL_ERROR = "tool_error"
    APPROVAL_PENDING = "approval_pending"
    CITATION_REJECTED = "citation_rejected"


class LoopEvent(str, Enum):
    """Stable ``TraceEntry.action`` names emitted by the loop."""

    STARTED = "loop_started"
    RESUMED = "loop_resumed"
    CONTEXT_SENSED = "context_sensed"
    ACTION_PLANNED = "action_planned"
    CITATIONS_REJECTED = "citations_rejected"
    TOOL_DISPATCHED = "tool_dispatched"
    COMPLETED = "loop_completed"
    PAUSED = "loop_paused"
    HALTED = "loop_halted"
    FAILED = "loop_failed"


@dataclass(frozen=True)
class AgentTask:
    """Validated runtime request for one session.

    Member 3's task contract is parsed and validated elsewhere. The loop only
    needs the goal to hand to the sensor and planner, and the identity the
    dispatcher uses for authorization and approval.
    """

    goal: str
    context: ExecutionContext

    def __post_init__(self) -> None:
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise ValueError("Agent task requires a goal.")
        if not isinstance(self.context, ExecutionContext):
            raise ValueError("Agent task requires an execution context.")


@dataclass(frozen=True)
class PlannedAction:
    """Read-only, detached copy of one planned ``ProposalSet``.

    ``ProposalSet.arguments`` is a mutable dict, so history and results keep
    this copy instead. ``to_proposal`` rebuilds a fresh ``ProposalSet`` when
    one is needed, for example for ``TestProposal.from_proposal_set``.
    """

    action: Action
    arguments: Mapping[str, Any]
    rationale: str
    evidence: tuple[EvidenceRef, ...]
    confidence: Confidence

    @classmethod
    def from_proposal(cls, proposal: ProposalSet) -> PlannedAction:
        """Copy and check a planner's proposal; raise if it is malformed."""

        if not isinstance(proposal, ProposalSet):
            raise TypeError("The planner must return a ProposalSet.")
        if not isinstance(proposal.rationale, str):
            raise TypeError("The proposal rationale must be a string.")
        evidence = tuple(proposal.evidence)
        for ref in evidence:
            if not (
                isinstance(ref, EvidenceRef)
                and isinstance(ref.source_path, str)
                and isinstance(ref.note, str)
            ):
                raise TypeError("Every evidence entry must be an EvidenceRef.")
        if not isinstance(proposal.arguments, Mapping):
            raise TypeError("The proposal arguments must be an object.")
        return cls(
            action=Action(proposal.action),
            arguments=_freeze_json(proposal.arguments),
            rationale=proposal.rationale,
            evidence=evidence,
            confidence=Confidence(proposal.confidence),
        )

    def to_proposal(self) -> ProposalSet:
        """Return a new ``ProposalSet`` whose arguments the caller may mutate."""

        return ProposalSet(
            action=self.action,
            arguments=_thaw(self.arguments),
            rationale=self.rationale,
            evidence=self.evidence,
            confidence=self.confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-ready representation."""

        return {
            "action": self.action.value,
            "arguments": _thaw(self.arguments),
            "rationale": self.rationale,
            "evidence": [
                {"source_path": ref.source_path, "note": ref.note}
                for ref in self.evidence
            ],
            "confidence": self.confidence.value,
        }


@dataclass(frozen=True)
class Observation:
    """Sanitized outcome of one turn that did not end the loop.

    ``message`` is a fixed loop-owned sentence, never exception text.
    ``output`` is set only for an executed tool and is a read-only copy of the
    dispatcher's validated, size-checked output.
    """

    iteration: int
    proposal: PlannedAction
    kind: ObservationKind
    message: str
    code: DispatchCode | None = None
    output: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-ready representation."""

        return {
            "iteration": self.iteration,
            "action": self.proposal.action.value,
            "arguments": _thaw(self.proposal.arguments),
            "kind": self.kind.value,
            "code": self.code.value if self.code else None,
            "message": self.message,
            "output": None if self.output is None else _thaw(self.output),
        }


@dataclass(frozen=True)
class LoopState:
    """Read-only session state given to the sensor, planner and stop evaluator."""

    session_id: str
    history: tuple[Observation, ...] = ()

    @property
    def iterations_completed(self) -> int:
        """Number of turns that produced an observation."""

        return len(self.history)

    def _with(self, observation: Observation) -> LoopState:
        return LoopState(
            session_id=self.session_id, history=(*self.history, observation)
        )


@dataclass(frozen=True)
class LoopResult:
    """Immutable outcome of one ``run`` or ``resume`` call.

    ``iterations`` counts every turn started in the session, including the
    final turn of a completed run. ``proposal`` is the validated final
    proposal for ``COMPLETED``/``NO_ACTION`` and the pending tool request for
    ``AWAITING_APPROVAL``. ``halt`` is set only for ``HALTED`` and ``failure``
    only for ``FAILED``.
    """

    status: LoopStatus
    task: AgentTask
    state: LoopState
    iterations: int
    message: str
    proposal: PlannedAction | None = None
    halt: LoopHaltEvent | None = None
    failure: LoopFailure | None = None

    @property
    def resumable(self) -> bool:
        return self.status is LoopStatus.AWAITING_APPROVAL


class ContextSensor(Protocol):
    """Gathers this turn's evidence, e.g. retrieval plus ``rag.build_context``."""

    def sense(self, task: AgentTask, state: LoopState) -> AssembledContext:
        """Return the context the planner may cite this turn."""


class Planner(Protocol):
    """Chooses the single next action, e.g. one propose_action model call."""

    def plan(
        self,
        task: AgentTask,
        context: AssembledContext,
        state: LoopState,
    ) -> ProposalSet:
        """Return exactly one structurally valid proposal."""


class Dispatcher(Protocol):
    """Executes one tool request; satisfied by ``orchestrator.ToolDispatcher``."""

    def dispatch(
        self,
        proposal: ProposalSet,
        *,
        context: ExecutionContext,
    ) -> DispatchResult:
        """Validate, authorize, approve and run at most one tool request."""


class StopEvaluator(Protocol):
    """Member 1's stop policy (iterations, time, repetition, no new information)."""

    def evaluate(self, state: LoopState) -> StopReason | None:
        """Return a ``StopReason`` to halt, or ``None`` to allow another turn."""


class TraceSink(Protocol):
    """Receives trace entries; Member 5's tracer owns formatting and storage."""

    def record(self, entry: TraceEntry) -> None:
        """Accept one trace entry."""


_OBSERVATION_KINDS = {
    DispatchStatus.EXECUTED: ObservationKind.TOOL_EXECUTED,
    DispatchStatus.REJECTED: ObservationKind.TOOL_REJECTED,
    DispatchStatus.TOOL_ERROR: ObservationKind.TOOL_ERROR,
    DispatchStatus.AWAITING_APPROVAL: ObservationKind.APPROVAL_PENDING,
}

_OBSERVATION_MESSAGES = {
    ObservationKind.TOOL_EXECUTED: "The tool executed successfully.",
    ObservationKind.TOOL_REJECTED: "The tool request was rejected and did not run.",
    ObservationKind.TOOL_ERROR: "The tool could not complete the request.",
    ObservationKind.APPROVAL_PENDING: "The tool request is waiting for human approval.",
    ObservationKind.CITATION_REJECTED: (
        "The proposal's evidence could not be traced to this turn's context, "
        "so it was not acted on."
    ),
}

_RESULT_MESSAGES = {
    LoopStatus.COMPLETED: "A validated test proposal is ready for human review.",
    LoopStatus.NO_ACTION: "The agent found no grounded action to take.",
    LoopStatus.AWAITING_APPROVAL: (
        "The loop is paused until the pending tool request is decided."
    ),
    LoopStatus.HALTED: "The loop was halted by its stop conditions.",
    LoopStatus.FAILED: "The loop stopped because a required component failed.",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _Abort(Exception):
    """Internal signal that a dependency failed and the loop must stop."""

    def __init__(self, failure: LoopFailure) -> None:
        super().__init__(failure.value)
        self.failure = failure


@dataclass
class _Run:
    """Mutable bookkeeping for one call; never exposed to callers."""

    task: AgentTask
    state: LoopState
    turns: int


class AgentLoop:
    """Drive one session until completion, a pause, a halt, or a failure."""

    def __init__(
        self,
        *,
        sensor: ContextSensor,
        planner: Planner,
        dispatcher: Dispatcher,
        stop_evaluator: StopEvaluator,
        trace_sink: TraceSink,
        clock: Callable[[], datetime] = _utc_now,
        max_observation_bytes: int = 64_000,
    ) -> None:
        _require(sensor, "sense", "context sensor")
        _require(planner, "plan", "planner")
        _require(dispatcher, "dispatch", "dispatcher")
        _require(stop_evaluator, "evaluate", "stop evaluator")
        _require(trace_sink, "record", "trace sink")
        if not callable(clock):
            raise ValueError("Agent loop requires a clock.")
        if max_observation_bytes <= 0:
            raise ValueError("Maximum observation size must be greater than zero.")
        self._sensor = sensor
        self._planner = planner
        self._dispatcher = dispatcher
        self._stop_evaluator = stop_evaluator
        self._trace_sink = trace_sink
        self._clock = clock
        self._max_observation_bytes = max_observation_bytes

    def run(self, task: AgentTask) -> LoopResult:
        """Start a new session for ``task``."""

        if not isinstance(task, AgentTask):
            raise TypeError("The agent loop requires an AgentTask.")
        state = LoopState(session_id=task.context.session_id)
        return self._drive(task, state, LoopEvent.STARTED)

    def resume(self, paused: LoopResult) -> LoopResult:
        """Continue a session that paused for approval.

        The loop never replays the pending request. Resuming checks the stop
        evaluator and then starts a fresh turn; if the planner proposes the
        same tool request again, it goes back through citation validation,
        the dispatcher and the approval gate like any other request.
        """

        if not isinstance(paused, LoopResult) or not paused.resumable:
            raise ValueError("Only a result that is awaiting approval can be resumed.")
        if paused.state.session_id != paused.task.context.session_id:
            raise ValueError("The paused state does not belong to this task.")
        return self._drive(paused.task, paused.state, LoopEvent.RESUMED)

    def _drive(
        self, task: AgentTask, state: LoopState, opening: LoopEvent
    ) -> LoopResult:
        run = _Run(task=task, state=state, turns=len(state.history))
        try:
            self._record(
                run, opening, f"iterations_completed={state.iterations_completed}"
            )
            # The stop evaluator runs before the first turn here and after
            # every observation in _observe, never anywhere else.
            reason = self._check_stop(run)
            if reason is not None:
                return self._halt(run, reason)
            while True:
                result = self._take_turn(run)
                if result is not None:
                    return result
        except _Abort as abort:
            return self._fail(run, abort.failure)

    def _take_turn(self, run: _Run) -> LoopResult | None:
        run.turns += 1
        turn = run.turns

        # Sense. The allow-list is snapshotted before planning so nothing the
        # planner does to the context object can widen what may be cited.
        context, allowed = self._sense(run)
        not_in_corpus = context.not_in_corpus is True
        self._record(
            run,
            LoopEvent.CONTEXT_SENSED,
            f"iteration={turn}; not_in_corpus={not_in_corpus}; "
            f"allowed_sources={len(allowed)}",
        )

        # Plan exactly one action.
        planned = self._plan(run, context)
        self._record(
            run,
            LoopEvent.ACTION_PLANNED,
            f"iteration={turn}; action={planned.action.value}; "
            f"confidence={planned.confidence.value}; "
            f"evidence={len(planned.evidence)}",
        )
        proposal = planned.to_proposal()

        # Validate before any dispatch. The no-evidence exception is derived
        # only from deterministic retrieval, never from the model's output.
        confirmed_not_in_corpus = not_in_corpus and not allowed
        try:
            validate_citations(
                proposal,
                allowed,
                confirmed_not_in_corpus=confirmed_not_in_corpus,
            )
        except UntraceableProposalError:
            # The expected US-8 rejection: observed, never dispatched, and
            # retried only if the stop evaluator allows another turn.
            rejected = Observation(
                iteration=turn,
                proposal=planned,
                kind=ObservationKind.CITATION_REJECTED,
                message=_OBSERVATION_MESSAGES[ObservationKind.CITATION_REJECTED],
            )
            return self._observe(run, rejected, LoopEvent.CITATIONS_REJECTED)
        except Exception:
            # Anything else is a validator fault, not a model mistake, so it
            # must not be retried as if the proposal were merely rejected.
            raise _Abort(LoopFailure.VALIDATION_FAILED) from None

        # Act. Direct actions finish here and are never dispatched.
        if planned.action is Action.PROPOSE_TEST:
            return self._finish(run, LoopStatus.COMPLETED, planned)
        if planned.action is Action.NO_ACTION:
            return self._finish(run, LoopStatus.NO_ACTION, planned)
        if planned.action not in TOOL_ACTIONS:
            raise _Abort(LoopFailure.PLAN_FAILED)
        observation = self._dispatch(run, planned, proposal)

        # Observe.
        return self._observe(run, observation, LoopEvent.TOOL_DISPATCHED)

    def _sense(self, run: _Run) -> tuple[AssembledContext, frozenset[str]]:
        try:
            context = self._sensor.sense(run.task, run.state)
            if not isinstance(context, AssembledContext):
                raise TypeError("The sensor must return an AssembledContext.")
            if isinstance(context.allowed_source_paths, str):
                raise TypeError("Allowed source paths must be a collection.")
            allowed = frozenset(context.allowed_source_paths)
            if not all(isinstance(path, str) for path in allowed):
                raise TypeError("Allowed source paths must be strings.")
        except Exception:
            raise _Abort(LoopFailure.SENSE_FAILED) from None
        return context, allowed

    def _plan(self, run: _Run, context: AssembledContext) -> PlannedAction:
        try:
            proposal = self._planner.plan(run.task, context, run.state)
            return PlannedAction.from_proposal(proposal)
        except Exception:
            raise _Abort(LoopFailure.PLAN_FAILED) from None

    def _dispatch(
        self, run: _Run, planned: PlannedAction, proposal: ProposalSet
    ) -> Observation:
        try:
            result = self._dispatcher.dispatch(proposal, context=run.task.context)
            if not isinstance(result, DispatchResult):
                raise TypeError("The dispatcher must return a DispatchResult.")
            kind = _OBSERVATION_KINDS[DispatchStatus(result.status)]
        except Exception:
            # Includes NOT_A_TOOL, which is impossible for a tool action.
            raise _Abort(LoopFailure.DISPATCH_FAILED) from None

        code = _dispatch_code(result.code)
        output = None
        if kind is ObservationKind.TOOL_EXECUTED:
            code = None
            try:
                output = self._bounded_output(result.output)
            except Exception:
                kind, code = ObservationKind.TOOL_ERROR, DispatchCode.INVALID_OUTPUT

        return Observation(
            iteration=run.turns,
            proposal=planned,
            kind=kind,
            message=_OBSERVATION_MESSAGES[kind],
            code=code,
            output=output,
        )

    def _bounded_output(self, output: Any) -> Mapping[str, Any]:
        # ToolDispatcher already validates and caps output; this keeps the
        # same guarantee for history if a different dispatcher is injected.
        if not isinstance(output, Mapping):
            raise TypeError("Tool output must be a mapping.")
        frozen = _freeze_json(output)
        if len(_encode_json(frozen)) > self._max_observation_bytes:
            raise ValueError("Tool output is too large for the observation history.")
        return frozen

    def _observe(
        self, run: _Run, observation: Observation, event: LoopEvent
    ) -> LoopResult | None:
        run.state = run.state._with(observation)
        invocation = None
        if event is LoopEvent.TOOL_DISPATCHED:
            invocation = self._trace_invocation(observation)
        code = observation.code.value if observation.code else "none"
        self._record(
            run,
            event,
            f"iteration={observation.iteration}; kind={observation.kind.value}; "
            f"code={code}",
            invocation=invocation,
        )

        reason = self._check_stop(run)
        if reason is not None:
            return self._halt(run, reason)
        if observation.kind is ObservationKind.APPROVAL_PENDING:
            # Pause rather than resubmit; the caller decides when to resume.
            return self._finish(run, LoopStatus.AWAITING_APPROVAL, observation.proposal)
        return None

    def _trace_invocation(self, observation: Observation) -> ToolInvocation:
        # Trace entries are persisted by Member 5, so they carry metadata
        # only: key names, status and size, never argument or output values
        # (queries, file content, tokens). The full bounded output stays in
        # the in-memory Observation for the next planning turn.
        output = observation.output
        return ToolInvocation(
            tool_name=observation.proposal.action.value,
            input={"argument_keys": sorted(observation.proposal.arguments)},
            output={
                "kind": observation.kind.value,
                "code": observation.code.value if observation.code else None,
                "output_keys": None if output is None else sorted(output),
                "output_bytes": None if output is None else len(_encode_json(output)),
            },
            called_at=self._clock(),
        )

    def _check_stop(self, run: _Run) -> StopReason | None:
        try:
            decision = self._stop_evaluator.evaluate(run.state)
            return None if decision is None else StopReason(decision)
        except Exception:
            raise _Abort(LoopFailure.STOP_CHECK_FAILED) from None

    def _halt(self, run: _Run, reason: StopReason) -> LoopResult:
        completed = run.state.iterations_completed
        halt = LoopHaltEvent(
            session_id=run.state.session_id,
            reason=reason,
            iteration_count=completed,
            halted_at=self._clock(),
        )
        self._record(
            run,
            LoopEvent.HALTED,
            f"reason={reason.value}; iterations_completed={completed}",
        )
        return self._result(run, LoopStatus.HALTED, halt=halt)

    def _finish(
        self, run: _Run, status: LoopStatus, proposal: PlannedAction
    ) -> LoopResult:
        event = (
            LoopEvent.PAUSED
            if status is LoopStatus.AWAITING_APPROVAL
            else LoopEvent.COMPLETED
        )
        self._record(
            run,
            event,
            f"iteration={run.turns}; status={status.value}; "
            f"action={proposal.action.value}",
        )
        return self._result(run, status, proposal=proposal)

    def _fail(self, run: _Run, failure: LoopFailure) -> LoopResult:
        if failure is not LoopFailure.TRACE_FAILED:
            try:
                self._record(run, LoopEvent.FAILED, f"failure={failure.value}")
            except _Abort:
                pass  # Report the original failure, not the trace failure.
        return self._result(run, LoopStatus.FAILED, failure=failure)

    def _record(
        self,
        run: _Run,
        event: LoopEvent,
        detail: str,
        *,
        invocation: ToolInvocation | None = None,
    ) -> None:
        # Details are built only from enums and counts, never from exception
        # text or free-form model output. A sink failure fails the loop
        # closed: actions must not continue without an audit trail (US-10).
        entry = TraceEntry(
            session_id=run.state.session_id,
            actor=Actor.AI if event is LoopEvent.ACTION_PLANNED else Actor.DETERMINISTIC,
            action=event.value,
            detail=detail,
            timestamp=self._clock(),
            tool_invocation=invocation,
        )
        try:
            self._trace_sink.record(entry)
        except Exception:
            raise _Abort(LoopFailure.TRACE_FAILED) from None

    @staticmethod
    def _result(
        run: _Run,
        status: LoopStatus,
        *,
        proposal: PlannedAction | None = None,
        halt: LoopHaltEvent | None = None,
        failure: LoopFailure | None = None,
    ) -> LoopResult:
        return LoopResult(
            status=status,
            task=run.task,
            state=run.state,
            iterations=run.turns,
            message=_RESULT_MESSAGES[status],
            proposal=proposal,
            halt=halt,
            failure=failure,
        )


def _require(dependency: Any, method: str, label: str) -> None:
    if not callable(getattr(dependency, method, None)):
        raise ValueError(f"Agent loop requires a {label}.")


def _dispatch_code(value: Any) -> DispatchCode | None:
    if value is None:
        return None
    try:
        return DispatchCode(value)
    except (TypeError, ValueError):
        return None


def _freeze_json(value: Any) -> Any:
    """Return a read-only deep copy of plain JSON data, or raise.

    Objects become ``MappingProxyType`` views over private dicts and arrays
    become tuples, so neither the caller nor a later stage can change what
    the loop recorded.
    """

    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings.")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite.")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("Value is not JSON-compatible.")


def _thaw(value: Any) -> Any:
    """Return a plain, mutable, JSON-ready deep copy of frozen data."""

    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _encode_json(value: Any) -> bytes:
    """Encode frozen JSON data the same compact way ToolDispatcher measures it."""

    return json.dumps(
        _thaw(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
