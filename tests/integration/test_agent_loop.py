"""Focused tests for Member 2's Week 5 agent loop.

Deterministic fakes stand in for the retrieval sensor, the model planner,
Member 1's stop evaluator and Member 5's trace sink. Tool requests go through
the real ToolDispatcher with fake tools, so the validate -> dispatch boundary
is exercised for real. These checks cover loop integration only; they do not
replace Member 4's stop-condition or execution-trace tests.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from unittest import mock

from agent import (
    AgentLoop,
    AgentTask,
    LoopFailure,
    LoopResult,
    LoopStatus,
    ObservationKind,
)
from models.types import (
    Action,
    Actor,
    Confidence,
    EvidenceRef,
    LoopHaltEvent,
    ProposalSet,
    StopReason,
    TraceEntry,
)
from orchestrator import (
    ApprovalStatus,
    ApprovalVerdict,
    DispatchCode,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRisk,
)
from rag import AssembledContext, IndexManifest, RetrievalResult, build_context


SOURCE = "tests/fixtures/member2/corpus/src/login_service.py"
REQUIREMENT = "tests/fixtures/member2/corpus/requirements/authentication.md"
FABRICATED = "pricing/discount_table.md"
SECRET = "test-secret-placeholder"
FIXED_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
CONTEXT = ExecutionContext(session_id="session-1", actor_id="dev-1", role="developer")
TASK = AgentTask(goal="Propose tests for the login lockout requirement.", context=CONTEXT)


def grounded_context(*paths: str) -> AssembledContext:
    paths = paths or (SOURCE, REQUIREMENT)
    return AssembledContext(
        text="<evidence>fixture</evidence>",
        chunks_used=len(paths),
        chunks_dropped=0,
        not_in_corpus=False,
        allowed_source_paths=frozenset(paths),
    )


def empty_corpus_context() -> AssembledContext:
    """Built by the real context builder from a not-in-corpus retrieval."""

    return build_context(
        RetrievalResult(
            query="refund policy for annual plans",
            chunks=(),
            not_in_corpus=True,
            manifest=IndexManifest(
                corpus_version="test",
                corpus_fingerprint="deadbeef",
                document_count=0,
                chunk_count=0,
            ),
            candidates_considered=0,
            top_score=0.0,
            top_term_coverage=0.0,
            latency_ms=0,
        )
    )


def proposal(action: Action, arguments=None, evidence=(SOURCE,)) -> ProposalSet:
    return ProposalSet(
        action=action,
        arguments={} if arguments is None else arguments,
        rationale="Grounded in the supplied context.",
        evidence=tuple(EvidenceRef(source_path=path) for path in evidence),
        confidence=Confidence.HIGH,
    )


def search(query: str = "lockout") -> ProposalSet:
    return proposal(Action.SEARCH_REPO, {"query": query})


def propose_test() -> ProposalSet:
    return proposal(Action.PROPOSE_TEST, {"title": "Lock account after five failures"})


class ScriptedSensor:
    def __init__(self, contexts, log) -> None:
        self.contexts = list(contexts) or [grounded_context()]
        self.log = log
        self.calls: list[tuple] = []

    def sense(self, task, state):
        self.log.append("sense")
        self.calls.append((task, state))
        return self.contexts[min(len(self.calls), len(self.contexts)) - 1]


class ScriptedPlanner:
    def __init__(self, proposals, log) -> None:
        self.proposals = list(proposals)
        self.log = log
        self.calls: list[tuple] = []

    def plan(self, task, context, state):
        self.log.append("plan")
        self.calls.append((task, context, state))
        if len(self.calls) > len(self.proposals):
            raise AssertionError("Planner called more often than scripted.")
        return self.proposals[len(self.calls) - 1]


class FakeStopEvaluator:
    """Stand-in for Member 1's evaluator: halt once N observations exist."""

    def __init__(self, halt_after, reason, log) -> None:
        self.halt_after = halt_after
        self.reason = reason
        self.log = log
        self.states: list = []

    def evaluate(self, state):
        self.log.append("stop")
        self.states.append(state)
        if self.halt_after is not None and state.iterations_completed >= self.halt_after:
            return self.reason
        return None


class RecordingTraceSink:
    def __init__(self) -> None:
        self.entries: list[TraceEntry] = []

    def record(self, entry) -> None:
        self.entries.append(entry)

    @property
    def actions(self) -> list[str]:
        return [entry.action for entry in self.entries]


class CountingDispatcher:
    """Wraps the real ToolDispatcher and records every call."""

    def __init__(self, dispatcher, log) -> None:
        self.dispatcher = dispatcher
        self.log = log
        self.calls: list[ProposalSet] = []

    def dispatch(self, proposal, *, context):
        self.log.append("dispatch")
        self.calls.append(proposal)
        return self.dispatcher.dispatch(proposal, context=context)


class FakeTool:
    """Minimal Member 3 tool stand-in that requires a ``query`` argument."""

    def __init__(
        self,
        name: str = "search_repo",
        *,
        risk: ToolRisk = ToolRisk.READ_ONLY,
        output=None,
        run_error: Exception | None = None,
        required: str | None = "query",
    ) -> None:
        self.name = name
        self.risk = risk
        self.allowed_roles = ("developer",)
        self.output = {"matches": [SOURCE]} if output is None else output
        self.run_error = run_error
        self.required = required
        self.runs: list[dict] = []

    def validate_arguments(self, arguments):
        if self.required is not None and self.required not in arguments:
            raise ValueError(f"missing argument; {SECRET}")
        return dict(arguments)

    def run(self, arguments, context):
        self.runs.append(arguments)
        if self.run_error is not None:
            raise self.run_error
        return self.output

    def validate_output(self, output):
        return dict(output)


class FakeGate:
    def __init__(self, status: ApprovalStatus) -> None:
        self.status = status
        self.calls: list[dict] = []

    def check(self, *, action, arguments, context):
        self.calls.append({"action": action, "arguments": arguments})
        return ApprovalVerdict(self.status)


class Harness:
    """Builds one loop from scripted fakes that share a call log."""

    def __init__(
        self,
        *proposals,
        contexts=(),
        tools=(),
        gate=None,
        halt_after=None,
        reason=StopReason.ITERATION_CAP,
        **overrides,
    ) -> None:
        self.log: list[str] = []
        self.sensor = ScriptedSensor(contexts, self.log)
        self.planner = ScriptedPlanner(proposals, self.log)
        self.dispatcher = CountingDispatcher(
            ToolDispatcher(ToolRegistry(tools), approval_gate=gate), self.log
        )
        self.stop = FakeStopEvaluator(halt_after, reason, self.log)
        self.trace = RecordingTraceSink()
        dependencies = {
            "sensor": self.sensor,
            "planner": self.planner,
            "dispatcher": self.dispatcher,
            "stop_evaluator": self.stop,
            "trace_sink": self.trace,
        }
        dependencies.update(overrides)
        self.loop = AgentLoop(clock=lambda: FIXED_NOW, **dependencies)

    def run(self) -> LoopResult:
        return self.loop.run(TASK)


TURN = ["sense", "plan", "dispatch", "stop"]


class CompletionTests(unittest.TestCase):
    def test_validated_direct_actions_complete_without_dispatch(self) -> None:
        cases = {
            Action.PROPOSE_TEST: LoopStatus.COMPLETED,
            Action.NO_ACTION: LoopStatus.NO_ACTION,
        }
        for action, status in cases.items():
            with self.subTest(action=action):
                h = Harness(proposal(action, {"title": "t"}), tools=[FakeTool()])

                result = h.run()

                self.assertIs(result.status, status)
                self.assertIs(result.proposal.action, action)
                self.assertEqual(result.iterations, 1)
                self.assertEqual(result.state.history, ())
                self.assertEqual(h.dispatcher.calls, [])
                self.assertEqual(h.log, ["stop", "sense", "plan"])

    def test_tool_observation_feeds_next_turn_before_completion(self) -> None:
        tool = FakeTool(output={"matches": [SOURCE]})
        h = Harness(search(), propose_test(), tools=[tool])

        result = h.run()

        self.assertIs(result.status, LoopStatus.COMPLETED)
        self.assertEqual(result.iterations, 2)
        self.assertEqual(h.log, ["stop", *TURN, "sense", "plan"])
        second_turn_state = h.planner.calls[1][2]
        observation = second_turn_state.history[0]
        self.assertIs(observation.kind, ObservationKind.TOOL_EXECUTED)
        self.assertEqual(observation.to_dict()["output"], {"matches": [SOURCE]})
        self.assertEqual(result.state.history, second_turn_state.history)
        self.assertEqual(len(tool.runs), 1)


class OneActionPerTurnTests(unittest.TestCase):
    def test_each_turn_plans_once_and_dispatches_at_most_once(self) -> None:
        tool = FakeTool()
        h = Harness(search("a"), search("b"), search("c"), tools=[tool], halt_after=3)

        result = h.run()

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertEqual(h.log, ["stop", *TURN, *TURN, *TURN])
        self.assertEqual(
            [call.arguments for call in h.dispatcher.calls],
            [{"query": "a"}, {"query": "b"}, {"query": "c"}],
        )
        self.assertEqual(len(tool.runs), 3)
        self.assertEqual([obs.iteration for obs in result.state.history], [1, 2, 3])
        self.assertEqual(
            result.halt,
            LoopHaltEvent(
                session_id="session-1",
                reason=StopReason.ITERATION_CAP,
                iteration_count=3,
                halted_at=FIXED_NOW,
            ),
        )


class CitationTests(unittest.TestCase):
    def test_untraceable_citation_is_rejected_before_dispatch(self) -> None:
        cases = {
            "fabricated": (FABRICATED,),
            "fabricated_among_valid": (SOURCE, FABRICATED),
            "missing": (),
        }
        for label, evidence in cases.items():
            with self.subTest(label):
                tool = FakeTool("read_file", required="path")
                h = Harness(
                    proposal(Action.READ_FILE, {"path": SOURCE}, evidence),
                    tools=[tool],
                    halt_after=1,
                )

                result = h.run()

                self.assertIs(result.status, LoopStatus.HALTED)
                self.assertEqual(h.dispatcher.calls, [])
                self.assertEqual(tool.runs, [])
                observation = result.state.history[0]
                self.assertIs(observation.kind, ObservationKind.CITATION_REJECTED)
                self.assertNotIn(FABRICATED, observation.message)
                self.assertIn("citations_rejected", h.trace.actions)

    def test_planner_cannot_widen_the_sensed_allow_list(self) -> None:
        mutable_paths = {SOURCE}
        context = AssembledContext(
            text="fixture",
            chunks_used=1,
            chunks_dropped=0,
            not_in_corpus=False,
            allowed_source_paths=mutable_paths,
        )

        class WideningPlanner(ScriptedPlanner):
            def plan(self, task, context, state):
                context.allowed_source_paths.add(FABRICATED)
                return super().plan(task, context, state)

        planner = WideningPlanner(
            [proposal(Action.SEARCH_REPO, {"query": "x"}, (FABRICATED,))], []
        )
        h = Harness(contexts=[context], tools=[FakeTool()], halt_after=1, planner=planner)

        result = h.run()

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertIs(result.state.history[0].kind, ObservationKind.CITATION_REJECTED)
        self.assertEqual(h.dispatcher.calls, [])

    def test_evidence_free_no_action_completes_for_confirmed_empty_corpus(self) -> None:
        h = Harness(
            proposal(Action.NO_ACTION, evidence=()),
            contexts=[empty_corpus_context()],
            tools=[FakeTool()],
        )

        result = h.run()

        self.assertIs(result.status, LoopStatus.NO_ACTION)
        self.assertEqual(result.proposal.evidence, ())
        self.assertEqual(h.dispatcher.calls, [])

    def test_evidence_free_no_action_is_rejected_when_corpus_is_not_confirmed_empty(
        self,
    ) -> None:
        def context(not_in_corpus: bool, *paths: str) -> AssembledContext:
            return AssembledContext(
                text="fixture",
                chunks_used=len(paths),
                chunks_dropped=0,
                not_in_corpus=not_in_corpus,
                allowed_source_paths=frozenset(paths),
            )

        for label, sensed in {
            "grounded": grounded_context(),
            "not_in_corpus_with_sources": context(True, SOURCE),
            "no_sources_without_confirmation": context(False),
        }.items():
            with self.subTest(label):
                h = Harness(
                    proposal(Action.NO_ACTION, evidence=()),
                    contexts=[sensed],
                    halt_after=1,
                )

                result = h.run()

                self.assertIs(result.status, LoopStatus.HALTED)
                self.assertIs(
                    result.state.history[0].kind, ObservationKind.CITATION_REJECTED
                )

    def test_empty_corpus_does_not_excuse_other_unsupported_proposals(self) -> None:
        cases = {
            "evidence_free_propose_test": proposal(Action.PROPOSE_TEST, evidence=()),
            "evidence_free_tool": proposal(Action.SEARCH_REPO, {"query": "x"}, ()),
            "no_action_with_fabricated_citation": proposal(
                Action.NO_ACTION, evidence=(FABRICATED,)
            ),
        }
        for label, planned in cases.items():
            with self.subTest(label):
                tool = FakeTool()
                h = Harness(
                    planned,
                    contexts=[empty_corpus_context()],
                    tools=[tool],
                    halt_after=1,
                )

                result = h.run()

                self.assertIs(result.status, LoopStatus.HALTED)
                self.assertIs(
                    result.state.history[0].kind, ObservationKind.CITATION_REJECTED
                )
                self.assertEqual(tool.runs, [])


class ApprovalTests(unittest.TestCase):
    def make(self, *proposals) -> tuple[Harness, FakeTool, FakeGate]:
        tool = FakeTool("run_tests", risk=ToolRisk.REQUIRES_APPROVAL, required="test_ids")
        gate = FakeGate(ApprovalStatus.PENDING)
        return Harness(*proposals, tools=[tool], gate=gate), tool, gate

    def run_tests(self) -> ProposalSet:
        return proposal(Action.RUN_TESTS, {"test_ids": ["test_lockout"]})

    def test_pending_approval_pauses_without_resubmitting(self) -> None:
        h, tool, gate = self.make(self.run_tests(), self.run_tests())

        result = h.run()

        self.assertIs(result.status, LoopStatus.AWAITING_APPROVAL)
        self.assertTrue(result.resumable)
        self.assertIs(result.proposal.action, Action.RUN_TESTS)
        self.assertEqual(h.log, ["stop", *TURN])
        self.assertEqual(len(gate.calls), 1)
        self.assertEqual(tool.runs, [])
        observation = result.state.history[-1]
        self.assertIs(observation.kind, ObservationKind.APPROVAL_PENDING)
        self.assertIs(observation.code, DispatchCode.APPROVAL_PENDING)
        self.assertEqual(h.trace.actions[-1], "loop_paused")

    def test_resume_starts_a_fresh_turn_and_never_replays_the_request(self) -> None:
        h, tool, gate = self.make(self.run_tests(), propose_test())
        paused = h.run()
        gate.status = ApprovalStatus.APPROVED

        resumed = h.loop.resume(paused)

        self.assertIs(resumed.status, LoopStatus.COMPLETED)
        self.assertEqual(resumed.iterations, 2)
        self.assertEqual(resumed.state.history, paused.state.history)
        self.assertEqual(h.log, ["stop", *TURN, "stop", "sense", "plan"])
        self.assertEqual(len(h.dispatcher.calls), 1)
        self.assertEqual(len(gate.calls), 1)
        self.assertEqual(tool.runs, [])
        self.assertIn("loop_resumed", h.trace.actions)

    def test_only_paused_results_can_be_resumed(self) -> None:
        h = Harness(propose_test())
        completed = h.run()

        for value in (completed, None, "awaiting_approval"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    h.loop.resume(value)


class ObservationRetryTests(unittest.TestCase):
    def assert_no_leak(self, result: LoopResult, trace: RecordingTraceSink) -> None:
        self.assertNotIn(SECRET, repr(result))
        self.assertNotIn(SECRET, repr(trace.entries))

    def test_rejected_request_is_observed_and_can_be_corrected(self) -> None:
        tool = FakeTool()
        bad = proposal(Action.SEARCH_REPO, {"pattern": "lockout"})
        h = Harness(bad, search(), propose_test(), tools=[tool])

        result = h.run()

        self.assertIs(result.status, LoopStatus.COMPLETED)
        self.assertEqual(
            [obs.kind for obs in result.state.history],
            [ObservationKind.TOOL_REJECTED, ObservationKind.TOOL_EXECUTED],
        )
        rejected = result.state.history[0]
        self.assertIs(rejected.code, DispatchCode.INVALID_ARGUMENTS)
        self.assertIsNone(rejected.output)
        self.assertEqual(len(tool.runs), 1)
        self.assert_no_leak(result, h.trace)

    def test_tool_errors_are_retried_only_while_stop_evaluator_allows(self) -> None:
        tool = FakeTool(run_error=RuntimeError(SECRET))
        h = Harness(
            *[search() for _ in range(5)],
            tools=[tool],
            halt_after=2,
            reason=StopReason.REPEATED_CALL_DETECTED,
        )

        result = h.run()

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertIs(result.halt.reason, StopReason.REPEATED_CALL_DETECTED)
        self.assertEqual(len(h.planner.calls), 2)
        self.assertEqual(len(tool.runs), 2)
        for observation in result.state.history:
            self.assertIs(observation.kind, ObservationKind.TOOL_ERROR)
            self.assertIs(observation.code, DispatchCode.EXECUTION_FAILED)
            self.assertIsNone(observation.output)
        self.assert_no_leak(result, h.trace)

    def test_oversized_output_becomes_a_tool_error_observation(self) -> None:
        h = Harness(
            search(),
            tools=[FakeTool(output={"blob": "x" * 500})],
            halt_after=1,
            max_observation_bytes=100,
        )

        result = h.run()

        observation = result.state.history[0]
        self.assertIs(observation.kind, ObservationKind.TOOL_ERROR)
        self.assertIs(observation.code, DispatchCode.INVALID_OUTPUT)
        self.assertIsNone(observation.output)


class StopTests(unittest.TestCase):
    def test_stop_before_first_turn_prevents_all_calls(self) -> None:
        h = Harness(search(), tools=[FakeTool()], halt_after=0)

        result = h.run()

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertEqual(result.iterations, 0)
        self.assertEqual(result.halt.iteration_count, 0)
        self.assertEqual(h.log, ["stop"])
        self.assertEqual(h.trace.actions, ["loop_started", "loop_halted"])
        self.assertIn("reason=iteration_cap", h.trace.entries[-1].detail)

    def test_stop_after_observation_prevents_further_calls(self) -> None:
        h = Harness(
            search("a"),
            search("b"),
            tools=[FakeTool()],
            halt_after=1,
            reason=StopReason.NO_NEW_INFORMATION,
        )

        result = h.run()

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertIs(result.halt.reason, StopReason.NO_NEW_INFORMATION)
        self.assertEqual(h.log, ["stop", *TURN])
        self.assertEqual(len(h.planner.calls), 1)

    def test_stop_evaluator_is_required(self) -> None:
        for evaluator in (None, object()):
            with self.subTest(evaluator=evaluator):
                with self.assertRaises(ValueError):
                    Harness(stop_evaluator=evaluator)


class ImmutabilityTests(unittest.TestCase):
    def test_loop_does_not_mutate_or_alias_caller_inputs(self) -> None:
        class MutatingTool(FakeTool):
            def validate_arguments(self, arguments):
                arguments["paths"].append("validate")
                return super().validate_arguments(arguments)

            def run(self, arguments, context):
                arguments["paths"].append("run")
                return super().run(arguments, context)

        arguments = {"query": "lockout", "paths": ["src"]}
        planned = proposal(Action.SEARCH_REPO, arguments)
        tool = MutatingTool(output={"matches": [SOURCE]})
        h = Harness(planned, propose_test(), tools=[tool])

        result = h.run()
        arguments["paths"].append("caller")
        tool.output["matches"].append("tampered")

        self.assertEqual(planned.arguments["paths"], ["src", "caller"])
        recorded = result.state.history[0].to_dict()
        self.assertEqual(recorded["arguments"], {"query": "lockout", "paths": ["src"]})
        self.assertEqual(recorded["output"], {"matches": [SOURCE]})
        self.assertIsNot(h.dispatcher.calls[0], planned)

    def test_results_and_history_are_read_only(self) -> None:
        h = Harness(search(), propose_test(), tools=[FakeTool()])

        result = h.run()
        observation = result.state.history[0]

        self.assertIsInstance(result.state.history, tuple)
        self.assertIsInstance(observation.output["matches"], tuple)
        with self.assertRaises(FrozenInstanceError):
            result.status = LoopStatus.FAILED
        with self.assertRaises(FrozenInstanceError):
            observation.output = {}
        with self.assertRaises(TypeError):
            observation.output["matches"] = ()
        with self.assertRaises(TypeError):
            result.proposal.arguments["title"] = "changed"

        detached = result.proposal.to_proposal()
        detached.arguments["title"] = "changed"
        result.proposal.to_dict()["arguments"]["title"] = "changed"
        self.assertEqual(
            result.proposal.arguments["title"], "Lock account after five failures"
        )


class TraceSeamTests(unittest.TestCase):
    def test_trace_sink_receives_lifecycle_events_in_order(self) -> None:
        h = Harness(search(), propose_test(), tools=[FakeTool()])

        h.run()

        self.assertEqual(
            h.trace.actions,
            [
                "loop_started",
                "context_sensed",
                "action_planned",
                "tool_dispatched",
                "context_sensed",
                "action_planned",
                "loop_completed",
            ],
        )
        for entry in h.trace.entries:
            self.assertIsInstance(entry, TraceEntry)
            self.assertEqual(entry.session_id, "session-1")
            self.assertEqual(entry.timestamp, FIXED_NOW)
            expected = Actor.AI if entry.action == "action_planned" else Actor.DETERMINISTIC
            self.assertIs(entry.actor, expected)
        dispatched = h.trace.entries[3].tool_invocation
        self.assertEqual(dispatched.tool_name, "search_repo")
        self.assertEqual(dispatched.input, {"argument_keys": ["query"]})

    def test_trace_payload_carries_metadata_not_argument_or_output_values(self) -> None:
        output = {"matches": [SOURCE], "content": f"password={SECRET}"}
        planned = proposal(
            Action.SEARCH_REPO, {"query": f"token {SECRET}", "path_scope": "src"}
        )
        h = Harness(planned, propose_test(), tools=[FakeTool(output=output)])

        result = h.run()

        self.assertIs(result.status, LoopStatus.COMPLETED)
        self.assertNotIn(SECRET, repr(h.trace.entries))
        invocation = h.trace.entries[3].tool_invocation
        self.assertEqual(invocation.tool_name, "search_repo")
        self.assertEqual(invocation.input, {"argument_keys": ["path_scope", "query"]})
        self.assertEqual(
            invocation.output,
            {
                "kind": "tool_executed",
                "code": None,
                "output_keys": ["content", "matches"],
                "output_bytes": len(
                    json.dumps(output, separators=(",", ":")).encode("utf-8")
                ),
            },
        )
        # The in-memory observation keeps the full bounded output because
        # the next planning turn needs it; only the trace is restricted.
        next_turn_history = h.planner.calls[1][2].history
        self.assertEqual(next_turn_history[0].output["content"], f"password={SECRET}")

    def test_rejected_tool_trace_has_status_without_output_metadata(self) -> None:
        h = Harness(
            proposal(Action.SEARCH_REPO, {"pattern": SECRET}),
            tools=[FakeTool()],
            halt_after=1,
        )

        h.run()

        invocation = h.trace.entries[3].tool_invocation
        self.assertNotIn(SECRET, repr(h.trace.entries))
        self.assertEqual(invocation.input, {"argument_keys": ["pattern"]})
        self.assertEqual(
            invocation.output,
            {
                "kind": "tool_rejected",
                "code": "invalid_arguments",
                "output_keys": None,
                "output_bytes": None,
            },
        )

    def test_trace_failure_fails_closed_before_any_action(self) -> None:
        class FailingSink:
            def record(self, entry):
                raise RuntimeError(SECRET)

        h = Harness(search(), tools=[FakeTool()], trace_sink=FailingSink())

        result = h.run()

        self.assertIs(result.status, LoopStatus.FAILED)
        self.assertIs(result.failure, LoopFailure.TRACE_FAILED)
        self.assertEqual(h.log, [])
        self.assertNotIn(SECRET, repr(result))


class Raising:
    """A dependency whose ``method`` raises an error carrying a secret."""

    def __init__(self, method: str) -> None:
        setattr(self, method, self._raise)

    @staticmethod
    def _raise(*args, **kwargs):
        raise RuntimeError(SECRET)


class Returning:
    """A dependency whose ``method`` returns a fixed, possibly invalid, value."""

    def __init__(self, method: str, value) -> None:
        setattr(self, method, lambda *args, **kwargs: value)



class FailClosedTests(unittest.TestCase):
    def test_component_failures_stop_the_loop_without_leaking_details(self) -> None:
        cases = {
            "sensor_raises": ({"sensor": Raising("sense")}, LoopFailure.SENSE_FAILED),
            "sensor_wrong_type": (
                {"sensor": Returning("sense", {"allowed_source_paths": [SOURCE]})},
                LoopFailure.SENSE_FAILED,
            ),
            "planner_raises": ({"planner": Raising("plan")}, LoopFailure.PLAN_FAILED),
            "planner_raw_text": (
                {"planner": Returning("plan", '{"action": "search_repo"}')},
                LoopFailure.PLAN_FAILED,
            ),
            "planner_non_json_arguments": (
                {"planner": Returning("plan", search(object()))},
                LoopFailure.PLAN_FAILED,
            ),
            "dispatcher_raises": (
                {"dispatcher": Raising("dispatch")},
                LoopFailure.DISPATCH_FAILED,
            ),
            "stop_evaluator_raises": (
                {"stop_evaluator": Raising("evaluate")},
                LoopFailure.STOP_CHECK_FAILED,
            ),
            "stop_evaluator_unknown_reason": (
                {"stop_evaluator": Returning("evaluate", "maybe")},
                LoopFailure.STOP_CHECK_FAILED,
            ),
        }
        for label, (overrides, failure) in cases.items():
            with self.subTest(label):
                tool = FakeTool()
                # halt_after bounds the run, so a regression fails instead of hanging.
                h = Harness(search(), search(), tools=[tool], halt_after=2, **overrides)

                result = h.run()

                self.assertIs(result.status, LoopStatus.FAILED)
                self.assertIs(result.failure, failure)
                self.assertEqual(tool.runs, [])
                self.assertEqual(h.trace.actions[-1], "loop_failed")
                self.assertNotIn(SECRET, repr(result))
                self.assertNotIn(SECRET, repr(h.trace.entries))

    def test_unexpected_validator_failure_fails_closed(self) -> None:
        tool = FakeTool()
        h = Harness(search(), search(), tools=[tool], halt_after=2)

        with mock.patch(
            "agent.loop.validate_citations", side_effect=RuntimeError(SECRET)
        ):
            result = h.run()

        self.assertIs(result.status, LoopStatus.FAILED)
        self.assertIs(result.failure, LoopFailure.VALIDATION_FAILED)
        self.assertEqual(result.state.history, ())
        self.assertEqual(h.log, ["stop", "sense", "plan"])
        self.assertEqual(tool.runs, [])
        self.assertNotIn("citations_rejected", h.trace.actions)
        self.assertEqual(h.trace.actions[-1], "loop_failed")
        self.assertNotIn(SECRET, repr(result))
        self.assertNotIn(SECRET, repr(h.trace.entries))

    def test_task_requires_goal_and_execution_context(self) -> None:
        for goal, context in (("", CONTEXT), ("   ", CONTEXT), ("goal", None)):
            with self.subTest(goal=goal, context=context):
                with self.assertRaises(ValueError):
                    AgentTask(goal=goal, context=context)


if __name__ == "__main__":
    unittest.main()
