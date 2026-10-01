"""Tests for src/agent/task_contract.yaml and its loader."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.task_contract import (
    DEFAULT_CONTRACT_PATH,
    TaskContractError,
    load_task_contract,
)
from models.types import AgentTaskContract
from tools.draft_issue import DraftIssueTool
from tools.read_file import ReadFileTool
from tools.run_tests import RunTestsTool
from tools.search_repo import SearchRepoTool

VALID = """\
goal: Propose grounded tests.
tools: [search_repo, read_file]
limits:
  max_iterations: 3
  wall_clock_budget_seconds: 10.5
"""


class ShippedContractTests(unittest.TestCase):
    def test_shipped_yaml_parses_into_the_dataclass(self) -> None:
        contract = load_task_contract()
        self.assertIsInstance(contract, AgentTaskContract)
        self.assertEqual(contract.max_iterations, 5)
        self.assertEqual(contract.wall_clock_budget_seconds, 120)
        self.assertTrue(contract.goal.startswith("You are the reasoning component"))

    def test_tools_match_the_tool_classes_names(self) -> None:
        names = {
            cls.name
            for cls in (SearchRepoTool, ReadFileTool, RunTestsTool, DraftIssueTool)
        }
        self.assertEqual(set(load_task_contract().tools), names)

    def test_goal_matches_the_prompt_role(self) -> None:
        prompt = DEFAULT_CONTRACT_PATH.parents[2] / "docs/prompts/propose_action/v1.1.md"
        text = " ".join(prompt.read_text(encoding="utf-8").split())
        goal = load_task_contract().goal
        for sentence in (
            "You are the reasoning component of a Software-Engineering QA Agent.",
            "You only propose.",
            "decide the ONE next action to take this turn.",
        ):
            self.assertIn(sentence, text)
            self.assertIn(sentence, goal)


class LoaderValidationTests(unittest.TestCase):
    def _load(self, text: str) -> AgentTaskContract:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.yaml"
            path.write_text(text, encoding="utf-8")
            return load_task_contract(path)

    def test_valid_file_matches_shape(self) -> None:
        self.assertEqual(
            self._load(VALID),
            AgentTaskContract(
                goal="Propose grounded tests.",
                tools=("search_repo", "read_file"),
                max_iterations=3,
                wall_clock_budget_seconds=10.5,
            ),
        )

    def test_rejects_bad_contracts(self) -> None:
        bad = {
            "unknown tool": VALID.replace("read_file", "delete_repo"),
            "propose_test is not a tool": VALID.replace("read_file", "propose_test"),
            "duplicate tool": VALID.replace("read_file", "search_repo"),
            "zero iterations": VALID.replace("max_iterations: 3", "max_iterations: 0"),
            "string iterations": VALID.replace("max_iterations: 3", 'max_iterations: "3"'),
            "bool iterations": VALID.replace("max_iterations: 3", "max_iterations: true"),
            "negative budget": VALID.replace("10.5", "-1"),
            "missing limits": "goal: x\ntools: [search_repo]\n",
            "unknown key": VALID + "extra: 1\n",
            "unknown limit key": VALID + "  retries: 1\n",
            "empty goal": VALID.replace("Propose grounded tests.", '""'),
            "not a mapping": "- a\n- b\n",
            "invalid yaml": "goal: [unclosed\n",
        }
        for label, text in bad.items():
            with self.subTest(label), self.assertRaises(TaskContractError):
                self._load(text)

    def test_missing_file(self) -> None:
        with self.assertRaises(TaskContractError):
            load_task_contract(Path("does/not/exist.yaml"))

    def test_dataclass_is_frozen(self) -> None:
        with self.assertRaises(AttributeError):
            load_task_contract().max_iterations = 99  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
