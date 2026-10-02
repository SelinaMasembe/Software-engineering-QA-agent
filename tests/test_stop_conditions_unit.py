"""Member 1's own unit tests for src/agent/stop_conditions.py.

Distinct from tests/test_stop_conditions.py (Member 4's Week 5 deliverable,
which tests a stand-in policy through the real AgentLoop and generates the
three evidence/traces/ runs). This file tests the real
agent.stop_conditions.StopConditionPolicy directly, in isolation, against
every condition and the precedence between them, including a couple of
cases Member 4's stand-in test file does not itself exercise (a non-positive
configuration beyond zero, and a non-callable clock).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from agent.loop import LoopState, Observation, ObservationKind, PlannedAction
from agent.stop_conditions import StopConditionPolicy
from models.types import Action, AgentTaskContract, Confidence, StopReason


class _FakeClock:
    """Deterministic, manually advanced clock for wall-clock tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self._now


def _observation(
    iteration: int,
    *,
    action: Action = Action.SEARCH_REPO,
    arguments: dict | None = None,
    kind: ObservationKind = ObservationKind.TOOL_EXECUTED,
    output: dict | None = None,
) -> Observation:
    proposal = PlannedAction(
        action=action,
        arguments={"query": f"q{iteration}"} if arguments is None else arguments,
        rationale="because",
        evidence=(),
        confidence=Confidence.HIGH,
    )
    return Observation(
        iteration=iteration,
        proposal=proposal,
        kind=kind,
        message="ok",
        output={"result": iteration} if output is None else output,
    )


def _state_with(*observations: Observation) -> LoopState:
    state = LoopState(session_id="session-1")
    for obs in observations:
        state = state._with(obs)
    return state


class ConstructionTests(unittest.TestCase):
    def test_rejects_non_positive_or_non_integer_max_iterations(self) -> None:
        for bad in (0, -1, 2.5, True, "5"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                StopConditionPolicy(max_iterations=bad, wall_clock_budget_seconds=60)

    def test_rejects_non_positive_wall_clock_budget(self) -> None:
        for bad in (0, -1, True, "60"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                StopConditionPolicy(max_iterations=5, wall_clock_budget_seconds=bad)

    def test_rejects_uncallable_clock(self) -> None:
        with self.assertRaises(ValueError):
            StopConditionPolicy(
                max_iterations=5,
                wall_clock_budget_seconds=60,
                clock="not callable",  # type: ignore[arg-type]
            )

    def test_from_contract_reads_the_contracts_limits(self) -> None:
        contract = AgentTaskContract(
            goal="g", tools=("search_repo",), max_iterations=3, wall_clock_budget_seconds=30
        )
        policy = StopConditionPolicy.from_contract(contract)
        self.assertEqual(policy.max_iterations, 3)
        self.assertEqual(policy.wall_clock_budget_seconds, 30)


class IterationCapTests(unittest.TestCase):
    def test_allows_continuation_with_no_history(self) -> None:
        policy = StopConditionPolicy(max_iterations=3, wall_clock_budget_seconds=100)
        self.assertIsNone(policy.evaluate(LoopState(session_id="s")))

    def test_allows_continuation_below_the_cap(self) -> None:
        policy = StopConditionPolicy(max_iterations=3, wall_clock_budget_seconds=100)
        state = _state_with(_observation(1), _observation(2))
        self.assertIsNone(policy.evaluate(state))

    def test_halts_exactly_at_the_configured_maximum(self) -> None:
        policy = StopConditionPolicy(max_iterations=2, wall_clock_budget_seconds=100)
        state = _state_with(_observation(1), _observation(2))
        self.assertEqual(policy.evaluate(state), StopReason.ITERATION_CAP)


class WallClockBudgetTests(unittest.TestCase):
    def test_allows_continuation_within_budget(self) -> None:
        clock = _FakeClock()
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=60, clock=clock)
        self.assertIsNone(policy.evaluate(LoopState(session_id="s")))
        clock.advance(30)
        self.assertIsNone(policy.evaluate(_state_with(_observation(1))))

    def test_halts_once_elapsed_time_reaches_the_budget(self) -> None:
        clock = _FakeClock()
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=60, clock=clock)
        self.assertIsNone(policy.evaluate(LoopState(session_id="s")))  # starts the clock
        clock.advance(60)
        self.assertEqual(
            policy.evaluate(_state_with(_observation(1))), StopReason.WALL_CLOCK_BUDGET
        )

    def test_start_time_is_fixed_on_first_evaluate_not_construction(self) -> None:
        clock = _FakeClock()
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=10, clock=clock)
        clock.advance(100)  # time passes before the loop ever calls evaluate()
        self.assertIsNone(policy.evaluate(LoopState(session_id="s")))

    def test_iteration_cap_takes_precedence_over_wall_clock(self) -> None:
        clock = _FakeClock()
        policy = StopConditionPolicy(max_iterations=1, wall_clock_budget_seconds=10, clock=clock)
        self.assertIsNone(policy.evaluate(LoopState(session_id="s")))
        clock.advance(100)
        state = _state_with(_observation(1))
        self.assertEqual(policy.evaluate(state), StopReason.ITERATION_CAP)


class RepeatedCallTests(unittest.TestCase):
    def test_varied_arguments_are_not_a_repeat(self) -> None:
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=100)
        state = _state_with(
            _observation(1, arguments={"query": "a"}),
            _observation(2, arguments={"query": "b"}),
        )
        self.assertIsNone(policy.evaluate(state))

    def test_identical_consecutive_action_and_arguments_is_detected(self) -> None:
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=100)
        state = _state_with(
            _observation(1, action=Action.SEARCH_REPO, arguments={"query": "a"}),
            _observation(2, action=Action.SEARCH_REPO, arguments={"query": "a"}),
        )
        self.assertEqual(policy.evaluate(state), StopReason.REPEATED_CALL_DETECTED)

    def test_a_repeat_that_is_not_the_two_most_recent_calls_is_not_flagged(self) -> None:
        # Matches the real team implementation's scope: only the immediately
        # preceding call is compared, not the whole history. A model that
        # returns to an earlier identical request, with something different
        # in between, is not caught by this check.
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=100)
        state = _state_with(
            _observation(1, action=Action.SEARCH_REPO, arguments={"query": "a"}),
            _observation(2, action=Action.READ_FILE, arguments={"path": "x"}),
            _observation(3, action=Action.SEARCH_REPO, arguments={"query": "a"}),
        )
        self.assertIsNone(policy.evaluate(state))


class NoNewInformationTests(unittest.TestCase):
    def test_different_output_is_not_stale(self) -> None:
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=100)
        state = _state_with(
            _observation(1, arguments={"query": "a"}, output={"result": 1}),
            _observation(2, arguments={"query": "b"}, output={"result": 2}),
        )
        self.assertIsNone(policy.evaluate(state))

    def test_identical_output_from_the_same_tool_is_detected(self) -> None:
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=100)
        state = _state_with(
            _observation(1, arguments={"query": "a"}, output={"result": "same"}),
            _observation(2, arguments={"query": "b"}, output={"result": "same"}),
        )
        self.assertEqual(policy.evaluate(state), StopReason.NO_NEW_INFORMATION)

    def test_identical_output_from_different_tools_is_also_flagged(self) -> None:
        # Matches the real team implementation: this check compares the two
        # most recent executed observations' output only, not their action,
        # so two different tools returning the same output still counts.
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=100)
        state = _state_with(
            _observation(1, action=Action.SEARCH_REPO, output={"result": "same"}),
            _observation(2, action=Action.READ_FILE, output={"result": "same"}),
        )
        self.assertEqual(policy.evaluate(state), StopReason.NO_NEW_INFORMATION)

    def test_a_non_executed_observation_immediately_before_breaks_the_check(self) -> None:
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=100)
        state = _state_with(
            _observation(1, output={"result": "same"}),
            _observation(2, kind=ObservationKind.CITATION_REJECTED, output=None),
            _observation(3, output={"result": "same"}),
        )
        self.assertIsNone(policy.evaluate(state))


class PrecedenceTests(unittest.TestCase):
    def test_repeated_call_is_reported_before_no_new_information(self) -> None:
        # A literal repeat (same action+arguments) also necessarily produces
        # the same output, so both conditions are true; the more specific
        # REPEATED_CALL_DETECTED must win per the documented check order.
        policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=100)
        state = _state_with(
            _observation(1, arguments={"query": "a"}, output={"result": "x"}),
            _observation(2, arguments={"query": "a"}, output={"result": "x"}),
        )
        self.assertEqual(policy.evaluate(state), StopReason.REPEATED_CALL_DETECTED)


if __name__ == "__main__":
    unittest.main()
