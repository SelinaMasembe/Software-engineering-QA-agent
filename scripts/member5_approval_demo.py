from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
from pathlib import Path

from models.types import Action, Confidence, EvidenceRef, ProposalSet
from orchestration.approval_gate import (
    AuditLogger,
    JSONApprovalGate,
    JSONApprovalStore,
)
from orchestration.tool_dispatcher import (
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
)
from tools.approval_tools import DraftIssueTool, RunTestsTool


def proposal(action: Action, arguments: dict) -> ProposalSet:
    return ProposalSet(
        action=action,
        arguments=arguments,
        rationale="Member 5 approval-gate demonstration.",
        evidence=(EvidenceRef(source_path="docs/requirements"),),
        confidence=Confidence.HIGH,
    )


def main() -> None:
    directory = Path(tempfile.mkdtemp(prefix="member5_demo_"))

    try:
        gate = JSONApprovalGate(
            store=JSONApprovalStore(str(directory / "approval_queue.json")),
            audit=AuditLogger(str(directory / "audit.log")),
            authorized_approvers={"Alice", "Bob"},
            timeout_seconds=3,
            poll_interval_seconds=0.1,
        )

        tools = ToolRegistry(
            [
                RunTestsTool(
                    sandbox_root=".",
                    manifest={
                        "dispatcher_tests": (
                            "python3",
                            "-m",
                            "unittest",
                            "tests.integration.test_tool_dispatcher",
                        )
                    },
                ),
                DraftIssueTool(str(directory)),
            ]
        )
        dispatcher = ToolDispatcher(tools, approval_gate=gate)
        context = ExecutionContext(
            session_id="demo-session",
            actor_id="qa-agent",
            role="qa_engineer",
        )

        def approve_pending() -> None:
            time.sleep(0.2)
            request = gate.store.list_pending()[0]
            gate.decide(
                request.id,
                approve=True,
                decided_by="Alice",
                reason="Approved for demonstration.",
            )

        thread = threading.Thread(target=approve_pending, daemon=True)
        thread.start()

        result = dispatcher.dispatch(
            proposal(
                Action.RUN_TESTS,
                {
                    "test_node_ids": ["dispatcher_tests"],
                    "session_id": "demo-session",
                },
            ),
            context=context,
        )
        print(json.dumps(result.to_dict(), indent=2))

        denied = dispatcher.dispatch(
            proposal(
                Action.RUN_TESTS,
                {
                    "test_node_ids": ["dispatcher_tests"],
                    "session_id": "demo-session",
                },
            ),
            context=context,
        )
        print(json.dumps(denied.to_dict(), indent=2))

    finally:
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    main()