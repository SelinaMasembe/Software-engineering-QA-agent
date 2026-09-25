from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from models.types import Action, Confidence, EvidenceRef, ProposalSet
from orchestrator import (
    ApprovalStatus,
    ApprovalVerdict,
    DispatchCode,
    DispatchStatus,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRegistryError,
    ToolRisk,
)


CONTEXT = ExecutionContext(
    session_id="session-1", actor_id="dev-1", role="developer"
)
SECRET = "test-secret-placeholder"


class FakeTool:
    """Minimal stand-in for a Member 3 tool; records every call it receives."""

    def __init__(
        self,
        name: str = "search_repo",
        *,
        risk: ToolRisk = ToolRisk.READ_ONLY,
        allowed_roles=("developer",),
        output=None,
        argument_error: Exception | None = None,
        run_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.risk = risk
        self.allowed_roles = allowed_roles
        self.output = {"matches": ["src/app.py"]} if output is None else output
        self.argument_error = argument_error
        self.run_error = run_error
        self.validated: list[dict] = []
        self.runs: list[tuple[dict, ExecutionContext]] = []

    def validate_arguments(self, arguments):
        self.validated.append(arguments)
        if self.argument_error is not None:
            raise self.argument_error
        return dict(arguments)

    def run(self, arguments, context):
        self.runs.append((arguments, context))
        if self.run_error is not None:
            raise self.run_error
        return self.output

    def validate_output(self, output):
        return dict(output)


class FakeGate:
    """Minimal stand-in for Member 5's approval gate."""

    def __init__(self, verdict) -> None:
        self.verdict = verdict
        self.calls: list[dict] = []

    def check(self, *, action, arguments, context):
        self.calls.append(
            {"action": action, "arguments": arguments, "context": context}
        )
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


def make_proposal(action=Action.SEARCH_REPO, arguments=None) -> ProposalSet:
    return ProposalSet(
        action=action,
        arguments={"query": "login"} if arguments is None else arguments,
        rationale="Find the login handler.",
        evidence=(EvidenceRef(source_path="src/app.py"),),
        confidence=Confidence.HIGH,
    )


def make_raw(action: str = "search_repo", arguments=None) -> str:
    return json.dumps(
        {
            "action": action,
            "arguments": {"query": "login"} if arguments is None else arguments,
            "rationale": "Find the login handler.",
            "evidence": [{"source_path": "src/app.py"}],
            "confidence": "high",
        }
    )


def make_dispatcher(*tools, gate=None, **kwargs) -> ToolDispatcher:
    return ToolDispatcher(ToolRegistry(tools), approval_gate=gate, **kwargs)


class ToolDispatcherTests(unittest.TestCase):
    def test_read_only_tool_executes_without_consulting_gate(self) -> None:
        tool = FakeTool()
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.DENIED))

        result = make_dispatcher(tool, gate=gate).dispatch(
            make_proposal(), context=CONTEXT
        )

        self.assertTrue(result.executed)
        self.assertIs(result.status, DispatchStatus.EXECUTED)
        self.assertIs(result.action, Action.SEARCH_REPO)
        self.assertIsNone(result.code)
        self.assertEqual(result.output, {"matches": ["src/app.py"]})
        self.assertEqual(tool.runs, [({"query": "login"}, CONTEXT)])
        self.assertEqual(gate.calls, [])

    def test_non_tool_action_is_not_executed(self) -> None:
        tool = FakeTool()

        for action in (Action.PROPOSE_TEST, Action.NO_ACTION):
            with self.subTest(action=action):
                result = make_dispatcher(tool).dispatch(
                    make_proposal(action, {}), context=CONTEXT
                )
                self.assertIs(result.status, DispatchStatus.NOT_A_TOOL)
                self.assertIs(result.action, action)
                self.assertIsNone(result.code)
                self.assertIsNone(result.output)
        self.assertEqual(tool.runs, [])

    def test_unregistered_tool_is_rejected(self) -> None:
        tool = FakeTool("search_repo")

        result = make_dispatcher(tool).dispatch(
            make_proposal(Action.READ_FILE, {"path": "src/app.py"}), context=CONTEXT
        )

        self.assertIs(result.status, DispatchStatus.REJECTED)
        self.assertIs(result.code, DispatchCode.UNKNOWN_TOOL)
        self.assertEqual(tool.runs, [])

    def test_unauthorized_role_is_rejected_before_validation(self) -> None:
        tool = FakeTool(allowed_roles=("maintainer",))

        result = make_dispatcher(tool).dispatch(make_proposal(), context=CONTEXT)

        self.assertIs(result.status, DispatchStatus.REJECTED)
        self.assertIs(result.code, DispatchCode.UNAUTHORIZED)
        self.assertEqual(tool.validated, [])
        self.assertEqual(tool.runs, [])

    def test_invalid_arguments_are_rejected(self) -> None:
        cases = {
            "raises": FakeTool(argument_error=ValueError(SECRET)),
            "non_dict": FakeTool(),
        }
        cases["non_dict"].validate_arguments = lambda arguments: [
            "not",
            "a",
            "dict",
        ]

        for label, tool in cases.items():
            with self.subTest(label):
                result = make_dispatcher(tool).dispatch(
                    make_proposal(), context=CONTEXT
                )
                self.assertIs(result.status, DispatchStatus.REJECTED)
                self.assertIs(result.code, DispatchCode.INVALID_ARGUMENTS)
                self.assertNotIn(SECRET, result.message)
                self.assertEqual(tool.runs, [])


class ApprovalTests(unittest.TestCase):
    def dispatch(self, gate):
        tool = FakeTool("run_tests", risk=ToolRisk.REQUIRES_APPROVAL)
        result = make_dispatcher(tool, gate=gate).dispatch(
            make_proposal(Action.RUN_TESTS, {"test_ids": ["t1"]}),
            context=CONTEXT,
        )
        return result, tool

    def test_missing_denied_or_pending_approval_blocks_execution(self) -> None:
        denied = FakeGate(ApprovalVerdict(ApprovalStatus.DENIED))
        pending = FakeGate(ApprovalVerdict(ApprovalStatus.PENDING))
        cases = [
            (None, DispatchStatus.REJECTED, DispatchCode.APPROVAL_GATE_MISSING),
            (denied, DispatchStatus.REJECTED, DispatchCode.APPROVAL_DENIED),
            (pending, DispatchStatus.AWAITING_APPROVAL, DispatchCode.APPROVAL_PENDING),
        ]
        for gate, status, code in cases:
            with self.subTest(code=code):
                result, tool = self.dispatch(gate)
                self.assertIs(result.status, status)
                self.assertIs(result.code, code)
                self.assertEqual(tool.runs, [])

    def test_approved_executes_once_with_validated_request(self) -> None:
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.APPROVED))

        result, tool = self.dispatch(gate)

        self.assertTrue(result.executed)
        self.assertEqual(len(tool.runs), 1)
        self.assertIs(gate.calls[0]["action"], Action.RUN_TESTS)
        self.assertEqual(gate.calls[0]["arguments"], {"test_ids": ["t1"]})
        self.assertEqual(gate.calls[0]["context"], CONTEXT)

    def test_malformed_or_failing_gate_fails_closed(self) -> None:
        verdicts = {
            "none": None,
            "no_status": object(),
            "unknown_status": SimpleNamespace(status="maybe"),
            "gate_raises": RuntimeError(SECRET),
        }
        for label, verdict in verdicts.items():
            with self.subTest(label):
                result, tool = self.dispatch(FakeGate(verdict))
                self.assertIs(result.status, DispatchStatus.REJECTED)
                self.assertIs(result.code, DispatchCode.APPROVAL_UNAVAILABLE)
                self.assertNotIn(SECRET, result.message)
                self.assertEqual(tool.runs, [])


class ToolFailureTests(unittest.TestCase):
    def test_tool_exception_is_reported_without_leaking_its_text(self) -> None:
        tool = FakeTool(run_error=RuntimeError(SECRET))

        result = make_dispatcher(tool).dispatch(make_proposal(), context=CONTEXT)

        self.assertIs(result.status, DispatchStatus.TOOL_ERROR)
        self.assertIs(result.code, DispatchCode.EXECUTION_FAILED)
        self.assertIsNone(result.output)
        self.assertNotIn(SECRET, json.dumps(result.to_dict()))

    def test_invalid_non_json_or_oversized_output_is_rejected(self) -> None:
        cases = {
            "not_a_mapping": (["src/app.py"], 64_000),
            "nan": ({"score": float("nan")}, 64_000),
            "non_json_value": ({"handle": object()}, 64_000),
            "oversized": ({"blob": "x" * 200}, 100),
        }
        for label, (output, limit) in cases.items():
            with self.subTest(label):
                tool = FakeTool(output=output)
                result = make_dispatcher(tool, max_output_bytes=limit).dispatch(
                    make_proposal(), context=CONTEXT
                )
                self.assertIs(result.status, DispatchStatus.TOOL_ERROR)
                self.assertIs(result.code, DispatchCode.INVALID_OUTPUT)
                self.assertIsNone(result.output)


class RequestNormalizationTests(unittest.TestCase):
    def test_malformed_raw_json_is_rejected(self) -> None:
        tool = FakeTool()
        raw_inputs = {
            "not_json": "search the repo please",
            "json_array": "[]",
            "missing_fields": json.dumps({"action": "search_repo"}),
            "unknown_action": make_raw(action="delete_repo"),
            "arguments_not_object": make_raw(arguments=["login"]),
            "not_a_string": None,
        }
        for label, raw in raw_inputs.items():
            with self.subTest(label):
                result = make_dispatcher(tool).dispatch_raw(raw, context=CONTEXT)
                self.assertIs(result.status, DispatchStatus.REJECTED)
                self.assertIs(result.code, DispatchCode.MALFORMED_REQUEST)
                self.assertIsNone(result.action)
        self.assertEqual(tool.runs, [])

    def test_string_valued_action_is_normalized(self) -> None:
        tool = FakeTool()

        result = make_dispatcher(tool).dispatch(
            make_proposal(action="search_repo"), context=CONTEXT
        )

        self.assertTrue(result.executed)
        self.assertIs(result.action, Action.SEARCH_REPO)
        self.assertIs(result.proposal.action, Action.SEARCH_REPO)

    def test_unknown_string_action_is_malformed(self) -> None:
        tool = FakeTool()

        result = make_dispatcher(tool).dispatch(
            make_proposal(action="delete_repo"), context=CONTEXT
        )

        self.assertIs(result.status, DispatchStatus.REJECTED)
        self.assertIs(result.code, DispatchCode.MALFORMED_REQUEST)
        self.assertIsNone(result.action)
        self.assertEqual(tool.runs, [])

    def test_callee_mutation_does_not_leak_between_stages(self) -> None:
        class MutatingTool(FakeTool):
            def validate_arguments(self, arguments):
                arguments["paths"].append("validate")
                return dict(arguments)

            def run(self, arguments, context):
                arguments["paths"].append("run")
                return super().run(arguments, context)

        class MutatingGate(FakeGate):
            def check(self, *, action, arguments, context):
                arguments["paths"].append("gate")
                return super().check(
                    action=action, arguments=arguments, context=context
                )

        tool = MutatingTool("run_tests", risk=ToolRisk.REQUIRES_APPROVAL)
        gate = MutatingGate(ApprovalVerdict(ApprovalStatus.APPROVED))
        proposal = make_proposal(Action.RUN_TESTS, {"paths": ["tests"]})

        result = make_dispatcher(tool, gate=gate).dispatch(
            proposal, context=CONTEXT
        )

        self.assertTrue(result.executed)
        self.assertEqual(proposal.arguments, {"paths": ["tests"]})
        self.assertEqual(result.proposal.arguments, {"paths": ["tests"]})
        self.assertEqual(
            gate.calls[0]["arguments"]["paths"], ["tests", "validate", "gate"]
        )
        self.assertEqual(
            tool.runs[0][0]["paths"], ["tests", "validate", "run"]
        )

    def test_to_dict_is_json_serialisable_and_detached(self) -> None:
        tool = FakeTool(output={"matches": ["src/app.py"]})
        result = make_dispatcher(tool).dispatch(make_proposal(), context=CONTEXT)

        result.to_dict()["output"]["matches"].append("tampered")
        tool.output["matches"].append("tampered")

        self.assertEqual(
            json.loads(json.dumps(result.to_dict())),
            {
                "status": "executed",
                "action": "search_repo",
                "code": None,
                "message": result.message,
                "latency_ms": result.latency_ms,
                "output": {"matches": ["src/app.py"]},
            },
        )


class ToolRegistryTests(unittest.TestCase):
    def test_unsafe_registrations_are_rejected(self) -> None:
        nameless = SimpleNamespace(
            risk=ToolRisk.READ_ONLY, allowed_roles=("developer",)
        )
        cases = {
            "duplicate": [FakeTool("search_repo"), FakeTool("search_repo")],
            "non_tool_action": [FakeTool("propose_test")],
            "unknown_name": [FakeTool("delete_repo")],
            "missing_name": [nameless],
            "unknown_risk": [FakeTool(risk="dangerous")],
            "empty_roles": [FakeTool(allowed_roles=())],
            "blank_roles": [FakeTool(allowed_roles=("", "   "))],
            "string_roles": [FakeTool(allowed_roles="developer")],
        }
        for label, tools in cases.items():
            with self.subTest(label):
                with self.assertRaises(ToolRegistryError):
                    ToolRegistry(tools)


if __name__ == "__main__":
    unittest.main()
