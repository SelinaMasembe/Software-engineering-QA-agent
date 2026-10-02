"""Member 5's approval gate with the real dispatcher and Member 3's tools.

``run_tests`` really runs one pytest node from tests/fixtures/sandbox through
Member 3's SandboxExecutor, so "executed" means a test actually ran.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models.types import Action, Actor, Confidence, EvidenceRef, ProposalSet
from orchestrator.approval_gate import (
    AuditLogger,
    JSONApprovalGate,
    JSONApprovalStore,
    SelfApprovalError,
    UnauthorizedApprover,
)
from orchestrator.router import (
    DispatchCode,
    DispatchStatus,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
)
from sandbox import SandboxExecutor
from tools import DraftIssueTool, DraftStore, RunTestsTool

PASSING_NODE = "tests/fixtures/sandbox/sample_cases.py::test_addition_passes"
ROLES = ("developer", "qa_engineer", "maintainer")


class CountingSandbox(SandboxExecutor):
    """The real sandbox, counting how many tests it actually ran."""

    def __init__(self) -> None:
        super().__init__()
        self.runs = 0

    def execute(self, test_node_id):
        self.runs += 1
        return super().execute(test_node_id)


class RecordingSink:
    def __init__(self) -> None:
        self.entries = []

    def record(self, entry) -> None:
        self.entries.append(entry)


class GateTestCase(unittest.TestCase):
    wait_seconds = 0.0

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="approval_test_"))
        self.queue_path = str(self.directory / "queue.json")
        self.gate = self.make_gate()
        self.context = ExecutionContext(
            session_id="test-session",
            actor_id="qa-agent",
            role="qa_engineer",
        )
        self.sandbox = CountingSandbox()
        self.tool = RunTestsTool({PASSING_NODE}, self.sandbox, allowed_roles=ROLES)

    def tearDown(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def make_gate(self, **overrides) -> JSONApprovalGate:
        options = {
            "store": JSONApprovalStore(self.queue_path),
            "audit": AuditLogger(str(self.directory / "audit.log")),
            "authorized_approvers": {"Alice", "Bob"},
            "wait_seconds": self.wait_seconds,
            "poll_interval_seconds": 0.05,
        }
        options.update(overrides)
        return JSONApprovalGate(**options)

    def dispatcher(self, gate: JSONApprovalGate | None = None) -> ToolDispatcher:
        return ToolDispatcher(ToolRegistry([self.tool]), approval_gate=gate or self.gate)

    def proposal(self, node_id: str = PASSING_NODE) -> ProposalSet:
        return ProposalSet(
            action=Action.RUN_TESTS,
            arguments={"test_node_ids": [node_id], "session_id": "test-session"},
            rationale="Run approved tests.",
            evidence=(EvidenceRef(source_path="tests"),),
            confidence=Confidence.HIGH,
        )

    def dispatch(self, gate: JSONApprovalGate | None = None):
        return self.dispatcher(gate).dispatch(self.proposal(), context=self.context)

    def pending(self):
        return self.gate.store.list_pending()


class BlockingModeTests(GateTestCase):
    """``wait_seconds > 0``: check() waits for the human, as in Week 4."""

    wait_seconds = 1.0

    def dispatch_in_background(self) -> tuple[threading.Thread, list]:
        holder: list = []
        worker = threading.Thread(target=lambda: holder.append(self.dispatch()))
        worker.start()
        time.sleep(0.2)
        return worker, holder

    def test_pending_request_does_not_execute(self) -> None:
        worker, holder = self.dispatch_in_background()

        self.assertEqual(len(self.pending()), 1)
        self.assertTrue(worker.is_alive())
        self.assertEqual(self.sandbox.runs, 0)

        self.gate.decide(self.pending()[0].id, approve=False, decided_by="Alice")
        worker.join(timeout=3)

        self.assertEqual(holder[0].code, DispatchCode.APPROVAL_DENIED)
        self.assertEqual(self.sandbox.runs, 0)

    def test_authorized_approval_executes(self) -> None:
        worker, holder = self.dispatch_in_background()
        self.gate.decide(self.pending()[0].id, approve=True, decided_by="Alice")
        worker.join(timeout=30)

        self.assertTrue(holder[0].executed)
        self.assertEqual(holder[0].output["results"][0]["outcome"], "pass")
        self.assertEqual(self.sandbox.runs, 1)

    def test_timeout_blocks_execution_and_expires_the_request(self) -> None:
        result = self.dispatch()

        self.assertEqual(result.code, DispatchCode.APPROVAL_DENIED)
        self.assertEqual(self.pending(), [])
        self.assertEqual([r.status for r in self.gate.store.all()], ["expired"])
        self.assertEqual(self.sandbox.runs, 0)

    def test_unknown_test_node_is_rejected_before_approval(self) -> None:
        result = self.dispatcher().dispatch(
            self.proposal("tests/unknown.py::test_nothing"), context=self.context
        )

        self.assertEqual(result.code, DispatchCode.INVALID_ARGUMENTS)
        self.assertEqual(self.gate.store.all(), [])

    def test_unauthorized_approver_does_not_kill_the_request(self) -> None:
        worker, holder = self.dispatch_in_background()
        request_id = self.pending()[0].id

        with self.assertRaises(UnauthorizedApprover):
            self.gate.decide(request_id, approve=True, decided_by="Mallory")
        self.assertEqual([r.id for r in self.pending()], [request_id])

        self.gate.decide(request_id, approve=True, decided_by="Alice")
        worker.join(timeout=30)

        self.assertTrue(holder[0].executed)

    def test_audit_records_request_decision_and_block(self) -> None:
        worker, holder = self.dispatch_in_background()
        self.gate.decide(
            self.pending()[0].id,
            approve=False,
            decided_by="Alice",
            reason="Not approved for this run.",
        )
        worker.join(timeout=3)

        audit_text = Path(self.gate.audit.path).read_text(encoding="utf-8")
        self.assertIn("approval_requested", audit_text)
        self.assertIn("decision_recorded", audit_text)
        self.assertIn("action_blocked", audit_text)
        self.assertIn("Not approved for this run.", audit_text)

    def test_draft_issue_needs_approval_and_is_never_submitted(self) -> None:
        store = DraftStore()
        dispatcher = ToolDispatcher(
            ToolRegistry([DraftIssueTool(store, allowed_roles=ROLES)]),
            approval_gate=self.gate,
        )
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
        holder: list = []
        worker = threading.Thread(
            target=lambda: holder.append(dispatcher.dispatch(proposal, context=self.context))
        )
        worker.start()
        time.sleep(0.2)
        self.assertEqual(store.all(), ())

        self.gate.decide(self.pending()[0].id, approve=True, decided_by="Bob")
        worker.join(timeout=3)

        self.assertTrue(holder[0].executed)
        self.assertEqual(holder[0].output["status"], "draft")
        self.assertEqual(len(store.all()), 1)


class NonBlockingModeTests(GateTestCase):
    """``wait_seconds = 0``: check() reports the current decision (agent loop)."""

    def test_first_check_returns_pending_without_running(self) -> None:
        result = self.dispatch()

        self.assertIs(result.status, DispatchStatus.AWAITING_APPROVAL)
        self.assertEqual(result.code, DispatchCode.APPROVAL_PENDING)
        self.assertEqual(len(self.pending()), 1)
        self.assertEqual(self.sandbox.runs, 0)

    def test_asking_again_while_pending_does_not_duplicate(self) -> None:
        self.dispatch()
        self.dispatch()
        self.dispatch()

        self.assertEqual(len(self.gate.store.all()), 1)

    def test_approval_runs_exactly_once_and_cannot_be_replayed(self) -> None:
        self.dispatch()
        self.gate.decide(self.pending()[0].id, approve=True, decided_by="Alice")

        first = self.dispatch()
        second = self.dispatch()

        self.assertTrue(first.executed)
        self.assertIs(second.status, DispatchStatus.AWAITING_APPROVAL)
        self.assertEqual(self.sandbox.runs, 1)
        self.assertEqual(len(self.gate.store.all()), 2)
        audit_text = Path(self.gate.audit.path).read_text(encoding="utf-8")
        self.assertIn("approval_consumed", audit_text)

    def test_denial_is_delivered_once(self) -> None:
        self.dispatch()
        self.gate.decide(self.pending()[0].id, approve=False, decided_by="Alice")

        self.assertEqual(self.dispatch().code, DispatchCode.APPROVAL_DENIED)
        self.assertEqual(self.dispatch().code, DispatchCode.APPROVAL_PENDING)
        self.assertEqual(self.sandbox.runs, 0)

    def test_requester_cannot_approve_their_own_request(self) -> None:
        self.context = ExecutionContext(
            session_id="test-session", actor_id="Alice", role="qa_engineer"
        )
        self.dispatch()
        request_id = self.pending()[0].id

        with self.assertRaises(SelfApprovalError):
            self.gate.decide(request_id, approve=True, decided_by="Alice")
        self.gate.decide(request_id, approve=True, decided_by="Bob")

        self.assertTrue(self.dispatch().executed)

    def test_undecided_request_expires_and_is_denied(self) -> None:
        now = [datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)]
        gate = self.make_gate(request_ttl_seconds=60, clock=lambda: now[0])
        self.dispatch(gate)
        request_id = gate.store.all()[0].id

        now[0] += timedelta(seconds=61)

        self.assertEqual(gate.store.list_pending(now=now[0]), [])
        with self.assertRaises(ValueError):
            gate.decide(request_id, approve=True, decided_by="Alice")
        self.assertEqual(self.dispatch(gate).code, DispatchCode.APPROVAL_DENIED)
        self.assertEqual(self.sandbox.runs, 0)

    def test_corrupt_queue_fails_closed(self) -> None:
        Path(self.queue_path).write_text("{not json", encoding="utf-8")

        result = self.dispatch()

        self.assertEqual(result.code, DispatchCode.APPROVAL_UNAVAILABLE)
        self.assertEqual(self.sandbox.runs, 0)

    def test_hand_edited_approval_by_an_unknown_approver_is_denied(self) -> None:
        self.dispatch()
        rows = json.loads(Path(self.queue_path).read_text(encoding="utf-8"))
        for row in rows.values():
            row.update(status="approved", decided_by="Mallory")
        Path(self.queue_path).write_text(json.dumps(rows), encoding="utf-8")

        self.assertEqual(self.dispatch().code, DispatchCode.APPROVAL_DENIED)
        self.assertEqual(self.sandbox.runs, 0)

    def test_concurrent_decisions_from_two_processes_cannot_both_win(self) -> None:
        self.dispatch()
        request_id = self.pending()[0].id
        # A second store on the same file stands in for the CLI process.
        cli_gate = self.make_gate(store=JSONApprovalStore(self.queue_path))
        outcomes: list[str] = []

        def decide(gate, approver, approve) -> None:
            try:
                gate.decide(request_id, approve=approve, decided_by=approver)
                outcomes.append("decided")
            except ValueError:
                outcomes.append("refused")

        workers = [
            threading.Thread(target=decide, args=(gate, approver, approve))
            for gate, approver, approve in (
                (self.gate, "Alice", True),
                (cli_gate, "Bob", False),
            )
            * 5
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)

        self.assertEqual(outcomes.count("decided"), 1)
        self.assertEqual(outcomes.count("refused"), 9)

    def test_human_decisions_are_sent_to_the_trace_sink(self) -> None:
        sink = RecordingSink()
        gate = self.make_gate(trace_sink=sink)
        self.dispatch(gate)
        gate.decide(gate.store.list_pending()[0].id, approve=True, decided_by="Alice")

        self.assertTrue(self.dispatch(gate).executed)

        self.assertEqual([entry.action for entry in sink.entries], ["approval_granted"])
        entry = sink.entries[0]
        self.assertIs(entry.actor, Actor.HUMAN)
        self.assertEqual(entry.session_id, "test-session")
        self.assertIn("approver=Alice", entry.detail)

    def test_trace_failure_fails_closed_and_keeps_the_approval(self) -> None:
        class FailingSink:
            def record(self, entry) -> None:
                raise OSError("disk full")

        self.dispatch()
        self.gate.decide(self.pending()[0].id, approve=True, decided_by="Alice")

        failed = self.dispatch(self.make_gate(trace_sink=FailingSink()))
        self.assertEqual(failed.code, DispatchCode.APPROVAL_UNAVAILABLE)
        self.assertEqual(self.sandbox.runs, 0)

        self.assertTrue(self.dispatch().executed)


if __name__ == "__main__":
    unittest.main()
