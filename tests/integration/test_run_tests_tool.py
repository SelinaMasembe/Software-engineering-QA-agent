from __future__ import annotations

import unittest

from models.types import Action, Confidence, EvidenceRef, ProposalSet
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
from sandbox import SandboxExecutor
from tools.run_tests import RunTestsTool

CONTEXT = ExecutionContext(session_id="session-1", actor_id="dev-1", role="developer")

FIXTURE_FILE = "tests/fixtures/sandbox/sample_cases.py"
PASSING_ID = f"{FIXTURE_FILE}::test_addition_passes"
FAILING_ID = f"{FIXTURE_FILE}::test_subtraction_deliberately_fails"

MANIFEST = frozenset(
    {
        "tests/test_config.py::ModelConfigurationTests::test_loads_model_settings_from_environment",
        "tests/integration/test_rag_pipeline.py::TokenizerTests::test_identifiers_are_split_into_searchable_words",
        PASSING_ID,
        FAILING_ID,
    }
)
KNOWN_ID = "tests/test_config.py::ModelConfigurationTests::test_loads_model_settings_from_environment"

VALID_ARGUMENTS = {"session_id": "session-1", "test_node_ids": [PASSING_ID]}


class CountingSandboxExecutor:
    """Wraps a real SandboxExecutor and records every execute() call, so a
    test can prove the dispatcher genuinely never reached run() -- not just
    infer it from the resulting status.
    """

    def __init__(self, real: SandboxExecutor) -> None:
        self._real = real
        self.calls: list[str] = []

    def execute(self, test_node_id: str):
        self.calls.append(test_node_id)
        return self._real.execute(test_node_id)


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
        action=Action.RUN_TESTS,
        arguments=dict(VALID_ARGUMENTS if arguments is None else arguments),
        rationale="Confirm the fix against its own regression test.",
        evidence=(EvidenceRef(source_path="requirements/auth.md"),),
        confidence=Confidence.HIGH,
    )


class RunTestsToolTests(unittest.TestCase):
    """Exercise the tool directly, without going through the dispatcher."""

    def setUp(self) -> None:
        self.tool = RunTestsTool(MANIFEST, SandboxExecutor())

    def test_satisfies_the_requires_approval_tool_protocol_declaration(self) -> None:
        self.assertEqual(self.tool.name, "run_tests")
        self.assertIs(self.tool.risk, ToolRisk.REQUIRES_APPROVAL)
        self.assertIn("developer", self.tool.allowed_roles)

    def test_valid_request_normalizes_cleanly(self) -> None:
        validated = self.tool.validate_arguments(VALID_ARGUMENTS)

        self.assertEqual(validated["session_id"], "session-1")
        self.assertEqual(validated["test_node_ids"], (PASSING_ID,))

    def test_missing_or_empty_test_node_ids_is_rejected(self) -> None:
        cases = {
            "missing": {"session_id": "session-1"},
            "empty_list": {"session_id": "session-1", "test_node_ids": []},
            "not_a_list": {"session_id": "session-1", "test_node_ids": "x"},
            "blank_entry": {"session_id": "session-1", "test_node_ids": [KNOWN_ID, "  "]},
        }
        for label, arguments in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    self.tool.validate_arguments(arguments)

    def test_missing_or_blank_session_id_is_rejected(self) -> None:
        for arguments in (
            {"test_node_ids": [KNOWN_ID]},
            {"session_id": "  ", "test_node_ids": [KNOWN_ID]},
            {"session_id": 5, "test_node_ids": [KNOWN_ID]},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    self.tool.validate_arguments(arguments)

    def test_unknown_test_node_id_is_rejected_against_the_manifest(self) -> None:
        arguments = {"session_id": "session-1", "test_node_ids": ["tests/nope.py::not_real"]}

        with self.assertRaises(ValueError):
            self.tool.validate_arguments(arguments)

    def test_extra_argument_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.validate_arguments({**VALID_ARGUMENTS, "extra": 1})

    def test_run_executes_a_real_test_through_the_sandbox(self) -> None:
        arguments = self.tool.validate_arguments(VALID_ARGUMENTS)

        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        self.assertEqual(output["session_id"], "session-1")
        self.assertEqual(len(output["results"]), 1)
        self.assertEqual(output["results"][0]["test_id"], PASSING_ID)
        self.assertEqual(output["results"][0]["outcome"], "pass")
        self.assertEqual(output["rejected"], [])

    def test_run_assembles_multiple_results_into_one_execution(self) -> None:
        arguments = self.tool.validate_arguments(
            {"session_id": "session-1", "test_node_ids": [PASSING_ID, FAILING_ID]}
        )

        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        self.assertEqual(output["session_id"], "session-1")
        outcomes = {entry["test_id"]: entry["outcome"] for entry in output["results"]}
        self.assertEqual(outcomes, {PASSING_ID: "pass", FAILING_ID: "fail"})
        self.assertEqual(output["rejected"], [])


class RunTestsValidateOutputTests(unittest.TestCase):
    """validate_output is fully testable independent of run()'s real
    execution -- build the SandboxExecutionResult-shaped dict by hand.
    """

    def setUp(self) -> None:
        self.tool = RunTestsTool(MANIFEST, SandboxExecutor())

    def test_accepts_a_well_formed_result(self) -> None:
        output = self.tool.validate_output(
            {
                "session_id": "session-1",
                "results": [
                    {
                        "test_id": KNOWN_ID,
                        "outcome": "pass",
                        "duration_ms": 12,
                        "stdout": "",
                        "stderr": "",
                    }
                ],
                "rejected": [
                    {"test_id": "tests/other.py::t", "reason": "outside_sandbox"}
                ],
            }
        )

        self.assertEqual(output["session_id"], "session-1")
        self.assertEqual(output["results"][0]["outcome"], "pass")
        self.assertEqual(output["rejected"][0]["reason"], "outside_sandbox")

    def test_defaults_rejected_to_empty_list(self) -> None:
        output = self.tool.validate_output(
            {"session_id": "session-1", "results": []}
        )

        self.assertEqual(output["rejected"], [])

    def test_rejects_an_unknown_outcome(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.validate_output(
                {
                    "session_id": "session-1",
                    "results": [
                        {
                            "test_id": KNOWN_ID,
                            "outcome": "maybe",
                            "duration_ms": 1,
                            "stdout": "",
                            "stderr": "",
                        }
                    ],
                }
            )

    def test_rejects_an_unknown_rejection_reason(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.validate_output(
                {
                    "session_id": "session-1",
                    "results": [],
                    "rejected": [{"test_id": KNOWN_ID, "reason": "because"}],
                }
            )

    def test_rejects_negative_duration(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.validate_output(
                {
                    "session_id": "session-1",
                    "results": [
                        {
                            "test_id": KNOWN_ID,
                            "outcome": "fail",
                            "duration_ms": -1,
                            "stdout": "",
                            "stderr": "",
                        }
                    ],
                }
            )


class RunTestsToolDispatcherIntegrationTests(unittest.TestCase):
    """Confirm the tool satisfies the Protocol at runtime, via the real
    ToolRegistry/ToolDispatcher, with a real SandboxExecutor -- no mocks,
    no stub error, actual subprocess execution end-to-end.
    """

    def setUp(self) -> None:
        self.sandbox = CountingSandboxExecutor(SandboxExecutor())
        self.tool = RunTestsTool(MANIFEST, self.sandbox)

    def make_dispatcher(self, gate) -> ToolDispatcher:
        return ToolDispatcher(ToolRegistry([self.tool]), approval_gate=gate)

    def test_approved_request_executes_for_real_end_to_end(self) -> None:
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.APPROVED))

        result = self.make_dispatcher(gate).dispatch(make_proposal(), context=CONTEXT)

        self.assertTrue(result.executed)
        self.assertIs(result.status, DispatchStatus.EXECUTED)
        self.assertEqual(result.output["session_id"], "session-1")
        self.assertEqual(result.output["results"][0]["test_id"], PASSING_ID)
        self.assertEqual(result.output["results"][0]["outcome"], "pass")
        self.assertEqual(len(gate.calls), 1)
        self.assertEqual(self.sandbox.calls, [PASSING_ID])

    def test_denied_request_never_reaches_run_or_the_sandbox(self) -> None:
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.DENIED))

        result = self.make_dispatcher(gate).dispatch(make_proposal(), context=CONTEXT)

        self.assertIs(result.status, DispatchStatus.REJECTED)
        self.assertIs(result.code, DispatchCode.APPROVAL_DENIED)
        self.assertEqual(self.sandbox.calls, [])

    def test_pending_request_never_reaches_run_or_the_sandbox(self) -> None:
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.PENDING))

        result = self.make_dispatcher(gate).dispatch(make_proposal(), context=CONTEXT)

        self.assertIs(result.status, DispatchStatus.AWAITING_APPROVAL)
        self.assertIs(result.code, DispatchCode.APPROVAL_PENDING)
        self.assertEqual(self.sandbox.calls, [])

    def test_unknown_test_node_id_is_rejected_before_the_gate_or_sandbox(self) -> None:
        gate = FakeGate(ApprovalVerdict(ApprovalStatus.APPROVED))
        proposal = make_proposal(
            {"session_id": "session-1", "test_node_ids": ["tests/nope.py::not_real"]}
        )

        result = self.make_dispatcher(gate).dispatch(proposal, context=CONTEXT)

        self.assertIs(result.status, DispatchStatus.REJECTED)
        self.assertIs(result.code, DispatchCode.INVALID_ARGUMENTS)
        self.assertEqual(gate.calls, [])
        self.assertEqual(self.sandbox.calls, [])


if __name__ == "__main__":
    unittest.main()
