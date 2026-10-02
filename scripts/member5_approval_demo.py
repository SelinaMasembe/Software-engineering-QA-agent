#!/usr/bin/env python3
"""Demonstrate Member 5's approval gate in front of Member 3's run_tests tool.

Three scenarios, all through the real ToolDispatcher:

1. Non-blocking check: the request is queued and reported as pending; nothing runs.
2. A human ("Alice") approves; the next identical request runs the test once.
3. The same request again: the approval was consumed, so it is pending again.

Queue and audit files go to a temporary directory that is deleted afterwards.

Run from the repository root:
    PYTHONPATH=src python3 scripts/member5_approval_demo.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models.types import Action, Confidence, EvidenceRef, ProposalSet  # noqa: E402
from orchestrator.approval_gate import (  # noqa: E402
    AuditLogger,
    JSONApprovalGate,
    JSONApprovalStore,
)
from orchestrator.router import (  # noqa: E402
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
)
from sandbox import SandboxExecutor  # noqa: E402
from tools import RunTestsTool  # noqa: E402

TEST_NODE = "tests/fixtures/sandbox/sample_cases.py::test_addition_passes"


def proposal() -> ProposalSet:
    return ProposalSet(
        action=Action.RUN_TESTS,
        arguments={"test_node_ids": [TEST_NODE], "session_id": "demo-session"},
        rationale="Member 5 approval-gate demonstration.",
        evidence=(EvidenceRef(source_path="tests/fixtures/sandbox/sample_cases.py"),),
        confidence=Confidence.HIGH,
    )


def show(title: str, result) -> None:
    summary = result.to_dict()
    if summary["output"]:
        summary["output"] = {
            "session_id": summary["output"]["session_id"],
            "results": [
                {key: item[key] for key in ("test_id", "outcome", "duration_ms")}
                for item in summary["output"]["results"]
            ],
        }
    print(f"\n=== {title}")
    print(json.dumps(summary, indent=2))


def main() -> None:
    directory = Path(tempfile.mkdtemp(prefix="member5_demo_"))

    try:
        gate = JSONApprovalGate(
            store=JSONApprovalStore(str(directory / "approval_queue.json")),
            audit=AuditLogger(str(directory / "audit.log")),
            authorized_approvers={"Alice", "Bob"},
        )
        dispatcher = ToolDispatcher(
            ToolRegistry(
                [
                    RunTestsTool(
                        {TEST_NODE},
                        SandboxExecutor(),
                        allowed_roles=("developer", "qa_engineer"),
                    )
                ]
            ),
            approval_gate=gate,
        )
        context = ExecutionContext(
            session_id="demo-session",
            actor_id="qa-agent",
            role="qa_engineer",
        )

        show("1. first request: queued, nothing runs", dispatcher.dispatch(proposal(), context=context))

        request = gate.store.list_pending()[0]
        gate.decide(
            request.id,
            approve=True,
            decided_by="Alice",
            reason="Approved for demonstration.",
        )
        print(f"\nAlice approved request {request.id}")

        show("2. same request after approval: runs once", dispatcher.dispatch(proposal(), context=context))
        show("3. same request again: approval was consumed", dispatcher.dispatch(proposal(), context=context))

        print("\n=== audit log")
        print((directory / "audit.log").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    main()
