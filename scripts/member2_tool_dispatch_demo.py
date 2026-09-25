#!/usr/bin/env python3
"""Demonstrate the Week 4 dispatcher with fixed, offline adapters.

The four scenarios show a read-only request executing, an approval-required
request being rejected without a gate, the same kind of request executing with
an approving demo gate, and an unknown action being rejected.  The ``Demo*``
classes below are not Member 3's production tools or Member 5's approval policy.
They return canned data, run no shell commands, and read no repository files.

Run from the repository root:
    python scripts/member2_tool_dispatch_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models.types import Action  # noqa: E402
from orchestration import (  # noqa: E402
    ApprovalStatus,
    ApprovalVerdict,
    DispatchCode,
    DispatchStatus,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRisk,
)

FIXTURE_PATH = "tests/fixtures/member2/corpus/src/login_service.py"
CONTEXT = ExecutionContext(
    session_id="demo-session", actor_id="demo-actor", role="developer"
)


class DemoSearchRepoTool:
    """Demo adapter standing in for Member 3's search_repo tool."""

    name = "search_repo"
    risk = ToolRisk.READ_ONLY
    allowed_roles = ("developer",)

    def __init__(self) -> None:
        self.runs = 0

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if set(arguments) != {"query"} or not isinstance(query, str) or not query:
            raise ValueError("The demo expects one non-empty query.")
        return {"query": query}

    def run(
        self,
        arguments: Mapping[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        self.runs += 1
        return {"query": arguments["query"], "matches": [FIXTURE_PATH]}

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        return {"query": str(output["query"]), "matches": list(output["matches"])}


class DemoRunTestsTool:
    """Demo adapter standing in for run_tests; it executes no tests."""

    name = "run_tests"
    risk = ToolRisk.REQUIRES_APPROVAL
    allowed_roles = ("developer",)

    def __init__(self) -> None:
        self.runs = 0

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        target = arguments.get("target")
        if set(arguments) != {"target"} or not isinstance(target, str) or not target:
            raise ValueError("The demo expects one non-empty target.")
        return {"target": target}

    def run(
        self,
        arguments: Mapping[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        self.runs += 1
        return {"target": arguments["target"], "passed": 3, "failed": 0}

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "target": str(output["target"]),
            "passed": int(output["passed"]),
            "failed": int(output["failed"]),
        }


class DemoApprovingGate:
    """Demo adapter standing in for Member 5's gate; not an approval policy."""

    def __init__(self) -> None:
        self.calls = 0

    def check(self, *, action, arguments, context) -> ApprovalVerdict:
        self.calls += 1
        return ApprovalVerdict(status=ApprovalStatus.APPROVED)


def make_raw(action: str, arguments: dict[str, Any]) -> str:
    return json.dumps(
        {
            "action": action,
            "arguments": arguments,
            "rationale": "Demo request.",
            "evidence": [{"source_path": FIXTURE_PATH}],
            "confidence": "high",
        }
    )


def sanitize(result_dict: dict[str, Any]) -> dict[str, Any]:
    """Remove timing variation from the printed evidence."""

    return {**result_dict, "latency_ms": 0}


def main() -> int:
    search_tool = DemoSearchRepoTool()
    tests_tool = DemoRunTestsTool()
    gate = DemoApprovingGate()
    registry = ToolRegistry([search_tool, tests_tool])
    ungated = ToolDispatcher(registry)
    gated = ToolDispatcher(registry, approval_gate=gate)
    run_tests_raw = make_raw("run_tests", {"target": "tests/demo"})

    scenarios = []

    result = ungated.dispatch_raw(
        make_raw("search_repo", {"query": "login"}), context=CONTEXT
    )
    assert result.status is DispatchStatus.EXECUTED, result
    assert result.action is Action.SEARCH_REPO and search_tool.runs == 1
    scenarios.append(("read_only_search_executes", result))

    result = ungated.dispatch_raw(run_tests_raw, context=CONTEXT)
    assert result.status is DispatchStatus.REJECTED, result
    assert result.code is DispatchCode.APPROVAL_GATE_MISSING, result
    assert result.output is None and tests_tool.runs == 0
    scenarios.append(("run_tests_without_gate_rejected", result))

    result = gated.dispatch_raw(run_tests_raw, context=CONTEXT)
    assert result.status is DispatchStatus.EXECUTED, result
    assert gate.calls == 1 and tests_tool.runs == 1
    scenarios.append(("run_tests_with_approving_gate_executes", result))

    result = gated.dispatch_raw(
        make_raw("delete_repository", {"confirm": True}), context=CONTEXT
    )
    assert result.status is DispatchStatus.REJECTED, result
    assert result.code is DispatchCode.MALFORMED_REQUEST and result.action is None
    assert gate.calls == 1 and search_tool.runs == 1 and tests_tool.runs == 1
    scenarios.append(("unknown_action_rejected", result))

    document = {
        "demo": "member2_tool_dispatch",
        "note": "Demo adapters only; no real tools or approval policy were used.",
        "scenarios": [
            {"scenario": name, "result": sanitize(result.to_dict())}
            for name, result in scenarios
        ],
    }
    encoded = json.dumps(document, indent=2, sort_keys=True)
    assert "Demo request." not in encoded, "Raw proposal content leaked."
    print(encoded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
