"""Tests for the contract -> AgentTask adapter."""

from __future__ import annotations

import unittest

from agent.loop import AgentTask, LoopState
from agent.stop_conditions import StopConditionPolicy
from agent.task_adapter import build_agent_task, build_stop_evaluator
from agent.task_contract import load_task_contract
from models.types import StopReason
from orchestrator import ExecutionContext

IDENTITY = {"session_id": "session-1", "actor_id": "dev-1", "role": "developer"}


class BuildAgentTaskTests(unittest.TestCase):
    def test_contract_goal_and_identity_reach_the_task(self) -> None:
        contract = load_task_contract()
        task = build_agent_task(contract, **IDENTITY)
        self.assertIsInstance(task, AgentTask)
        self.assertEqual(task.goal, contract.goal)
        self.assertEqual(
            task.context,
            ExecutionContext(session_id="session-1", actor_id="dev-1", role="developer"),
        )

    def test_rejects_invalid_or_missing_runtime_values(self) -> None:
        contract = load_task_contract()
        for field in IDENTITY:
            for bad in ("", "   ", " padded ", None):
                with self.subTest(field=field, value=bad), self.assertRaises(ValueError):
                    build_agent_task(contract, **{**IDENTITY, field: bad})
        with self.assertRaises(TypeError):
            build_agent_task(contract, session_id="s", actor_id="a")  # type: ignore[call-arg]

    def test_rejects_a_non_contract(self) -> None:
        with self.assertRaises(TypeError):
            build_agent_task({"goal": "x"}, **IDENTITY)  # type: ignore[arg-type]


class StopEvaluatorSeamTests(unittest.TestCase):
    # The seam described in the Week 4 version of this file is now closed:
    # build_stop_evaluator returns a real, working StopConditionPolicy
    # instead of raising StopEvaluatorNotImplementedError. These tests
    # replace the old "the seam is still open" placeholder.

    def test_returns_a_working_stop_condition_policy(self) -> None:
        contract = load_task_contract()
        evaluator = build_stop_evaluator(contract)
        self.assertIsInstance(evaluator, StopConditionPolicy)
        self.assertEqual(evaluator.max_iterations, contract.max_iterations)
        self.assertEqual(
            evaluator.wall_clock_budget_seconds, contract.wall_clock_budget_seconds
        )

    def test_evaluator_actually_enforces_the_contracts_iteration_cap(self) -> None:
        # Not just a type check: the returned object must really halt at the
        # contract's own limit, using the shipped task_contract.yaml values.
        contract = load_task_contract()
        evaluator = build_stop_evaluator(contract)
        state = LoopState(session_id="session-1")

        self.assertIsNone(evaluator.evaluate(state))

        for _ in range(contract.max_iterations):
            state = state._with(_dummy_observation(len(state.history) + 1))

        self.assertEqual(evaluator.evaluate(state), StopReason.ITERATION_CAP)

    def test_rejects_a_non_contract(self) -> None:
        with self.assertRaises(TypeError):
            build_stop_evaluator({"max_iterations": 5})  # type: ignore[arg-type]


def _dummy_observation(iteration: int):
    from agent.loop import Observation, ObservationKind, PlannedAction
    from models.types import Action, Confidence

    proposal = PlannedAction(
        action=Action.SEARCH_REPO,
        arguments={"query": f"turn-{iteration}"},
        rationale="r",
        evidence=(),
        confidence=Confidence.HIGH,
    )
    return Observation(
        iteration=iteration,
        proposal=proposal,
        kind=ObservationKind.TOOL_EXECUTED,
        message="ok",
        output={"turn": iteration},
    )


if __name__ == "__main__":
    unittest.main()
