"""Tests for the contract -> AgentTask adapter."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.loop import AgentTask
from agent.task_adapter import (
    StopEvaluatorNotImplementedError,
    build_agent_task,
    build_stop_evaluator,
)
from agent.task_contract import load_task_contract
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
    def test_raises_specific_error_naming_the_interface_and_limits(self) -> None:
        with self.assertRaises(StopEvaluatorNotImplementedError) as caught:
            build_stop_evaluator(load_task_contract())
        message = str(caught.exception)
        self.assertIn("evaluate(state: LoopState) -> StopReason | None", message)
        self.assertIn("max_iterations=5", message)
        self.assertIn("wall_clock_budget_seconds=120", message)

    def test_seam_is_still_open(self) -> None:
        # Fails when Member 1 lands stop_conditions.py, as a prompt to wire the
        # real evaluator into build_stop_evaluator and replace this test.
        path = Path(__file__).resolve().parents[1] / "src/agent/stop_conditions.py"
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
