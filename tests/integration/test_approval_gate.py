from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from models.types import Action, Confidence, EvidenceRef, ProposalSet
from orchestrator.approval_gate import (
    AuditLogger,
    JSONApprovalGate,
    JSONApprovalStore,
    UnauthorizedApprover,
)
from orchestrator.router import (
    ApprovalStatus,
    DispatchCode,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
)
from tools.approval_tools import DraftIssueTool, RunTestsTool


class ApprovalGateIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="approval_test_"))
        self.gate = JSONApprovalGate(
            store=JSONApprovalStore(str(self.directory / "queue.json")),
            audit=AuditLogger(str(self.directory / "audit.log")),
            authorized_approvers={"Alice", "Bob"},
            timeout_seconds=1,
            poll_interval_seconds=0.05,
        )
        self.context = ExecutionContext(
            session_id="test-session",
            actor_id="qa-agent",
            role="qa_engineer",
        )
        self.tool = RunTestsTool(
            sandbox_root=".",
            manifest={
                "dispatcher_tests": (
                    "python3",
                    "-m",
                    "unittest",
                    "tests.integration.test_tool_dispatcher",
                )
            },
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def _dispatcher(self) -> ToolDispatcher:
        return ToolDispatcher(
            ToolRegistry([self.tool]),
            approval_gate=self.gate,
        )

    def _proposal(self, node_id="dispatcher_tests") -> ProposalSet:
        return ProposalSet(
            action=Action.RUN_TESTS,
            arguments={
                "test_node_ids": [node_id],
                "session_id": "test-session",
            },
            rationale="Run approved tests.",
            evidence=(EvidenceRef(source_path="tests"),),
            confidence=Confidence.HIGH,
        )

    def test_pending_request_does_not_execute(self) -> None:
        result_holder = []

        def dispatch() -> None:
            result_holder.append(
                self._dispatcher().dispatch(
                    self._proposal(),
                    context=self.context,
                )
            )

        worker = threading.Thread(target=dispatch)
        worker.start()
        time.sleep(0.2)

        self.assertEqual(len(self.gate.store.list_pending()), 1)
        self.assertTrue(worker.is_alive())

        request = self.gate.store.list_pending()[0]
        self.gate.decide(request.id, approve=False, decided_by="Alice")
        worker.join(timeout=3)

        self.assertEqual(result_holder[0].code, DispatchCode.APPROVAL_DENIED)

    def test_authorized_approval_executes(self) -> None:
        def approve() -> None:
            time.sleep(0.1)
            request = self.gate.store.list_pending()[0]
            self.gate.decide(request.id, approve=True, decided_by="Alice")

        threading.Thread(target=approve, daemon=True).start()

        result = self._dispatcher().dispatch(
            self._proposal(),
            context=self.context,
        )

        self.assertTrue(result.executed)

    def test_timeout_blocks_execution(self) -> None:
        result = self._dispatcher().dispatch(
            self._proposal(),
            context=self.context,
        )

        self.assertEqual(result.code, DispatchCode.APPROVAL_DENIED)

    def test_unknown_test_node_is_rejected_before_approval(self) -> None:
        result = self._dispatcher().dispatch(
            self._proposal("unknown"),
            context=self.context,
        )

        self.assertEqual(result.code, DispatchCode.INVALID_ARGUMENTS)
        self.assertEqual(self.gate.store.list_pending(), [])

    def test_draft_issue_is_not_submitted(self) -> None:
        draft_tool = DraftIssueTool(str(self.directory))
        dispatcher = ToolDispatcher(ToolRegistry([draft_tool]))

        proposal = ProposalSet(
            action=Action.DRAFT_ISSUE,
            arguments={
                "title": "Example failure",
                "body": "A test failed.",
                "evidence_refs": ["tests/example.py"],
            },
            rationale="Create a reviewable draft.",
            evidence=(EvidenceRef(source_path="tests/example.py"),),
            confidence=Confidence.HIGH,
        )

        result = dispatcher.dispatch(proposal, context=self.context)

        self.assertTrue(result.executed)
        self.assertEqual(result.output["status"], "draft")


    def test_unauthorized_approver_is_rejected(self) -> None:
        result_holder = []

        def dispatch() -> None:
            result_holder.append(
                self._dispatcher().dispatch(
                    self._proposal(),
                    context=self.context,
                )
            )

        worker = threading.Thread(target=dispatch)
        worker.start()
        time.sleep(0.2)

        pending = self.gate.store.list_pending()
        self.assertEqual(len(pending), 1)

        with self.assertRaises(UnauthorizedApprover):
            self.gate.decide(
                pending[0].id,
                approve=True,
                decided_by="Mallory",
                reason="Unauthorized test decision.",
            )

        worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(result_holder), 1)
        self.assertEqual(
            result_holder[0].code,
            DispatchCode.APPROVAL_DENIED,
        )

    def test_audit_records_request_decision_and_block(self) -> None:
        result_holder = []

        def dispatch() -> None:
            result_holder.append(
                self._dispatcher().dispatch(
                    self._proposal(),
                    context=self.context,
                )
            )

        worker = threading.Thread(target=dispatch)
        worker.start()
        time.sleep(0.2)

        pending = self.gate.store.list_pending()
        self.assertEqual(len(pending), 1)

        self.gate.decide(
            pending[0].id,
            approve=False,
            decided_by="Alice",
            reason="Not approved for this run.",
        )

        worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(result_holder), 1)

        audit_text = Path(self.gate.audit.path).read_text(encoding="utf-8")

        self.assertIn("approval_requested", audit_text)
        self.assertIn("decision_recorded", audit_text)
        self.assertIn("action_blocked", audit_text)
        self.assertIn("Not approved for this run.", audit_text)


if __name__ == "__main__":
    unittest.main()