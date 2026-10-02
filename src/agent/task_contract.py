"""Load src/agent/task_contract.yaml into ``models.types.AgentTaskContract``.

This module only parses and validates the file. The agent loop does not call
it yet; a later adapter builds ``AgentTask`` and the stop evaluator's limits
from the result.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from models.types import AgentTaskContract

DEFAULT_CONTRACT_PATH = Path(__file__).with_name("task_contract.yaml")

_TOP_LEVEL_KEYS = {"goal", "tools", "limits"}
_LIMIT_KEYS = {"max_iterations", "wall_clock_budget_seconds"}


class TaskContractError(ValueError):
    """The task contract file is missing, malformed, or invalid."""


def load_task_contract(path: Path | str = DEFAULT_CONTRACT_PATH) -> AgentTaskContract:
    """Read and validate the contract at ``path``; raise ``TaskContractError``."""

    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise TaskContractError("The task contract could not be read.") from exc

    if not isinstance(raw, dict):
        raise TaskContractError("The task contract must be a mapping.")
    _check_keys(raw, _TOP_LEVEL_KEYS, "task contract")

    limits = raw["limits"]
    if not isinstance(limits, dict):
        raise TaskContractError("The task contract 'limits' must be a mapping.")
    _check_keys(limits, _LIMIT_KEYS, "limits")

    tools = raw["tools"]
    if not isinstance(tools, list):
        raise TaskContractError("The task contract 'tools' must be a list.")

    try:
        return AgentTaskContract(
            goal=raw["goal"],
            tools=tuple(tools),
            max_iterations=limits["max_iterations"],
            wall_clock_budget_seconds=limits["wall_clock_budget_seconds"],
        )
    except ValueError as exc:
        raise TaskContractError(str(exc)) from exc


def _check_keys(section: dict, expected: set[str], label: str) -> None:
    missing = sorted(expected - section.keys())
    unknown = sorted(str(key) for key in section.keys() - expected)
    if missing:
        raise TaskContractError(f"The {label} is missing: {', '.join(missing)}.")
    if unknown:
        raise TaskContractError(f"The {label} has unknown keys: {', '.join(unknown)}.")
