"""Member 1's Week 5 stop evaluator: enforces US-9's four stop conditions.

``agent.task_adapter.build_stop_evaluator`` documents the exact interface
this module must satisfy: a ``StopEvaluator`` (``agent.loop.StopEvaluator``)
built from ``contract.max_iterations`` and
``contract.wall_clock_budget_seconds``, exposing
``evaluate(state: LoopState) -> StopReason | None``. ``agent.loop.AgentLoop``
calls it before the first turn of every ``run()`` or ``resume()`` and again
after every recorded observation, never anywhere else, so this module is the
one place US-9's four stop conditions are actually enforced rather than only
described.

Four conditions, checked in this order: a hard iteration cap, a wall-clock
budget, detection of an identical repeated call, and a step that yields no
new information. All four are ``StopReason`` values already defined in
``models.types`` (Week 2); this module is what actually raises them.

Behaviour deliberately matches Member 4's real Week 5 deliverable,
``tests/test_stop_conditions.py``, rather than an independent re-derivation.
That file's own docstring calls its embedded ``StopConditionPolicy`` a
"stand-in... pending src/agent/stop_conditions.py," so this module is built
to be a behavioural drop-in for it: same constructor shape (keyword-only
``max_iterations``, ``wall_clock_budget_seconds``, ``clock``), same
precedence order, and the same two interpretation choices Member 4's version
makes, which are narrower than what an earlier draft of this module used:

- "An identical repeated call" compares only the two most recent recorded
  proposals (the latest against the one immediately before it), not every
  earlier proposal in history. A model that repeats an action it used two or
  more turns ago, with something different in between, is not flagged by
  this check; only an immediate back-to-back repeat is.
- "No new information" compares the two most recent observations' output
  directly whenever both are ``ObservationKind.TOOL_EXECUTED``, regardless
  of whether they came from the same action. It does not require the two
  calls to be the same tool, only that both executed and produced identical
  output back to back. An observation of any other kind (an error, a
  rejection) breaks the check rather than being skipped over.

``LoopState`` carries no timestamps, only ``session_id`` and an
``Observation`` history, so the wall-clock budget is this object's own
responsibility, not something it can read off the state. The policy records
its own start time on its first ``evaluate()`` call, using the same
injectable-clock pattern ``agent.loop.AgentLoop`` itself uses for
testability, and compares elapsed time against the budget from then on. One
consequence: the same ``StopConditionPolicy`` instance must be reused across
a ``run()`` and any later ``resume()`` of the same session; constructing a
fresh instance at resume time would silently reset the clock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from agent.loop import LoopState, Observation, ObservationKind
from models.types import StopReason


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StopConditionPolicy:
    """Deterministic implementation of ``agent.loop.StopEvaluator``.

    Construct one instance per agent session, from the limits in the
    session's ``AgentTaskContract``, and pass it to ``AgentLoop`` as
    ``stop_evaluator``. Reuse the same instance across any ``resume()``
    call for the same session; a freshly constructed instance starts its
    wall-clock budget over again.
    """

    def __init__(
        self,
        *,
        max_iterations: int,
        wall_clock_budget_seconds: float,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if (
            isinstance(max_iterations, bool)
            or not isinstance(max_iterations, int)
            or max_iterations <= 0
        ):
            raise ValueError("max_iterations must be a positive integer.")
        if (
            isinstance(wall_clock_budget_seconds, bool)
            or not isinstance(wall_clock_budget_seconds, (int, float))
            or wall_clock_budget_seconds <= 0
        ):
            raise ValueError("wall_clock_budget_seconds must be greater than zero.")
        if not callable(clock):
            raise ValueError("StopConditionPolicy requires a clock.")

        self.max_iterations = max_iterations
        self.wall_clock_budget_seconds = wall_clock_budget_seconds
        self._clock = clock
        self._started_at: datetime | None = None

    @classmethod
    def from_contract(
        cls,
        contract: "object",
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> "StopConditionPolicy":
        """Build directly from an ``AgentTaskContract``-shaped object.

        Accepts anything with ``max_iterations`` and
        ``wall_clock_budget_seconds`` attributes, so callers do not need to
        unpack the contract by hand.
        """

        return cls(
            max_iterations=contract.max_iterations,
            wall_clock_budget_seconds=contract.wall_clock_budget_seconds,
            clock=clock,
        )

    def evaluate(self, state: LoopState) -> StopReason | None:
        """Return a ``StopReason`` to halt, or ``None`` to allow another turn.

        Called by ``AgentLoop`` before the first turn of a session and
        after every recorded observation. The first call also marks this
        policy's own start time, used for the wall-clock check below.
        """

        if self._started_at is None:
            self._started_at = self._clock()

        if state.iterations_completed >= self.max_iterations:
            return StopReason.ITERATION_CAP

        elapsed_seconds = (self._clock() - self._started_at).total_seconds()
        if elapsed_seconds >= self.wall_clock_budget_seconds:
            return StopReason.WALL_CLOCK_BUDGET

        if _is_repeated_call(state.history):
            return StopReason.REPEATED_CALL_DETECTED

        if _yields_no_new_information(state.history):
            return StopReason.NO_NEW_INFORMATION

        return None


def _is_repeated_call(history: tuple[Observation, ...]) -> bool:
    """True if the identical action and arguments were just requested again,
    comparing only the two most recent proposals."""

    if len(history) < 2:
        return False
    latest, previous = history[-1], history[-2]
    return (
        latest.proposal.action == previous.proposal.action
        and latest.proposal.arguments == previous.proposal.arguments
    )


def _yields_no_new_information(history: tuple[Observation, ...]) -> bool:
    """True if the two most recent observations both executed a tool and
    produced byte-for-byte identical output."""

    if len(history) < 2:
        return False
    latest, previous = history[-1], history[-2]
    if latest.kind is not ObservationKind.TOOL_EXECUTED:
        return False
    if previous.kind is not ObservationKind.TOOL_EXECUTED:
        return False
    return latest.output == previous.output
