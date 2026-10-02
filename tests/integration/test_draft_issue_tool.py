from __future__ import annotations

import unittest

from models.types import Action, Confidence, DraftStatus, EvidenceRef, ProposalSet
from orchestrator import (
    ApprovalStatus,
    ApprovalVerdict,
    DispatchCode,
    DispatchStatus,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRisk,
)
from tools.draft_issue import DraftIssueTool, DraftStore

CONTEXT = ExecutionContext(session_id="session-1", actor_id="dev-1", role="developer")

VALID_ARGUMENTS = {
    "title": "Login accepts an incorrect password",
    "body": "The login handler does not reject a wrong password on retry.",
    "evidence_refs": ["requirements/auth.md", "src/login_service.py"],
}


class FakeGate:
    """Minimal stand-in for Member 5's approval gate, matching
    test_tool_dispatcher.py's FakeGate exactly -- there is no real
    approval_gate.py yet to use instead.
    """

    def __init__(self, verdict) -> None:
        self.verdict = verdict
        self.calls: list[dict] = []

    def check(self, *, action, arguments, context):
        self.calls.append({"action": action, "arguments": arguments, "context": context})
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


def make_proposal(arguments=None) -> ProposalSet:
    return ProposalSet(
        action=Action.DRAFT_ISSUE,
        arguments=dict(VALID_ARGUMENTS if arguments is None else arguments),
        rationale="Draft an issue for the reproduced login defect.",
        evidence=(EvidenceRef(source_path="requirements/auth.md"),),
        confidence=Confidence.HIGH,
    )


class DraftIssueToolTests(unittest.TestCase):
    """Exercise the tool directly, without going through the dispatcher."""

    def setUp(self) -> None:
        self.store = DraftStore()
        self.tool = DraftIssueTool(self.store, id_factory=lambda: "draft-1")

    def test_satisfies_the_requires_approval_tool_protocol_declaration(self) -> None:
        self.assertEqual(self.tool.name, "draft_issue")
        self.assertIs(self.tool.risk, ToolRisk.REQUIRES_APPROVAL)
        self.assertIn("developer", self.tool.allowed_roles)

    def test_run_persists_the_draft_and_returns_it(self) -> None:
        arguments = self.tool.validate_arguments(VALID_ARGUMENTS)
        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        self.assertEqual(output["draft_id"], "draft-1")
        self.assertEqual(output["title"], VALID_ARGUMENTS["title"])
        self.assertEqual(output["evidence_refs"], VALID_ARGUMENTS["evidence_refs"])
        self.assertEqual(output["status"], DraftStatus.DRAFT.value)

        persisted = self.store.get("draft-1")
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.title, VALID_ARGUMENTS["title"])
        self.assertEqual(persisted.evidence_refs, tuple(VALID_ARGUMENTS["evidence_refs"]))
        self.assertIs(persisted.status, DraftStatus.DRAFT)

    def test_empty_evidence_refs_is_rejected_at_validation(self) -> None:
        arguments = {**VALID_ARGUMENTS, "evidence_refs": []}

        with self.assertRaises(ValueError):
            self.tool.validate_arguments(arguments)
        self.assertEqual(self.store.all(), ())

    def test_missing_or_blank_title_or_body_is_rejected(self) -> None:
        cases = {
            "missing_title": {"body": "x", "evidence_refs": ["a.md"]},
            "blank_title": {**VALID_ARGUMENTS, "title": "   "},
            "missing_body": {"title": "x", "evidence_refs": ["a.md"]},
            "blank_body": {**VALID_ARGUMENTS, "body": ""},
            "non_string_evidence_entry": {**VALID_ARGUMENTS, "evidence_refs": ["a.md", 5]},
            "extra_argument": {**VALID_ARGUMENTS, "extra": 1},
        }
        for label, arguments in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    self.tool.validate_arguments(arguments)

    def test_never_imports_a_github_or_http_client(self) -> None:
        import ast

        import tools.draft_issue as module

        tree = ast.parse(open(module.__file__, encoding="utf-8").read())
        imported_modules = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        disallowed = {"github", "pygithub", "requests", "urllib", "httpx", "socket"}
        self.assertEqual(imported_modules & disallowed, set())


class DraftIssueToolDispatcherIntegrationTests(unittest.TestCase):
    """Confirm the tool satisfies the Protocol at runtime, via the real
    ToolRegistry/ToolDispatcher -- not just structurally.
    """

    def setUp(self) -> None:
        self.store = DraftStore()
        tool = DraftIssueTool(self.store, id_factory=lambda: "draft-1")
        self.tool = tool

    def make_dispatcher(self, gate) -> ToolDispatcher:
        return ToolDispatcher(ToolRegistry([self.tool]), approval_gate=gate)

    def test_approved_draft_executes_and_is_persisted(self) -> None:
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.APPROVED))

        result = self.make_dispatcher(gate).dispatch(make_proposal(), context=CONTEXT)

        self.assertTrue(result.executed)
        self.assertIs(result.status, DispatchStatus.EXECUTED)
        self.assertEqual(result.output["status"], DraftStatus.DRAFT.value)
        self.assertIsNotNone(self.store.get("draft-1"))
        self.assertEqual(len(gate.calls), 1)
        self.assertIs(gate.calls[0]["action"], Action.DRAFT_ISSUE)

    def test_denied_draft_is_rejected_and_never_persisted(self) -> None:
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.DENIED))

        result = self.make_dispatcher(gate).dispatch(make_proposal(), context=CONTEXT)

        self.assertIs(result.status, DispatchStatus.REJECTED)
        self.assertIs(result.code, DispatchCode.APPROVAL_DENIED)
        self.assertIsNone(result.output)
        self.assertEqual(self.store.all(), ())

    def test_pending_draft_awaits_approval_and_run_is_never_reached(self) -> None:
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.PENDING))

        result = self.make_dispatcher(gate).dispatch(make_proposal(), context=CONTEXT)

        self.assertIs(result.status, DispatchStatus.AWAITING_APPROVAL)
        self.assertIs(result.code, DispatchCode.APPROVAL_PENDING)
        self.assertIsNone(result.output)
        # The dispatcher never calls run() on PENDING, so nothing is stored --
        # this is dispatcher-owned behavior, not something the tool decides.
        self.assertEqual(self.store.all(), ())

    def test_missing_approval_gate_blocks_execution_without_persisting(self) -> None:
        dispatcher = ToolDispatcher(ToolRegistry([self.tool]))  # no gate configured

        result = dispatcher.dispatch(make_proposal(), context=CONTEXT)

        self.assertIs(result.status, DispatchStatus.REJECTED)
        self.assertIs(result.code, DispatchCode.APPROVAL_GATE_MISSING)
        self.assertEqual(self.store.all(), ())

    def test_empty_evidence_refs_is_rejected_before_the_gate_is_consulted(self) -> None:
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.APPROVED))
        proposal = make_proposal({**VALID_ARGUMENTS, "evidence_refs": []})

        result = self.make_dispatcher(gate).dispatch(proposal, context=CONTEXT)

        self.assertIs(result.status, DispatchStatus.REJECTED)
        self.assertIs(result.code, DispatchCode.INVALID_ARGUMENTS)
        self.assertEqual(gate.calls, [])
        self.assertEqual(self.store.all(), ())


if __name__ == "__main__":
    unittest.main()
