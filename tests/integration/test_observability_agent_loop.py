"""Integration tests for Member 2's Week 7 observability instrumentation.

The agent loop runs for real here: real retrieval over the Member 2 fixture
corpus, the real context builder, the real citation validator and the real
ToolDispatcher. Only the model, the tools and the stop policy are
deterministic fakes. The checks cover two things: the records describe what
the model did, what was retrieved, which tools ran and how long each step
took; and wrapping the loop's collaborators changes nothing the loop decides.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent import AgentLoop, AgentTask, LoopFailure, LoopStatus, ObservationKind
from agent.runner import build_agent_session
from models.client import ModelCallResult, TokenUsage
from models.types import (
    Action,
    AgentTaskContract,
    Confidence,
    EvidenceRef,
    ProposalSet,
    StopReason,
)
from observability import RunLogger, load_index, load_run
from observability.instrumentation import (
    ObservedDispatcher,
    ObservedModelClient,
    ObservedRetrievalPipeline,
    instrument_loop,
)
from observability.telemetry import (
    InMemoryStepSink,
    JsonlStepSink,
    ObservabilityRecorder,
    StepKind,
)
from orchestrator import (
    ApprovalStatus,
    ApprovalVerdict,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRisk,
)
from rag import build_context, build_retrieval_pipeline, load_documents_from_directory

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "tests" / "fixtures" / "member2" / "corpus"
REQUIREMENT = "requirements/authentication.md"
SOURCE = "src/login_service.py"
TEST_LOG = "logs/test_run_2026_09_15.txt"
FABRICATED = "pricing/discount_table.md"
SECRET = "test-secret-placeholder"
FIXED_NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
SESSION = "week7-observability"
CONTEXT = ExecutionContext(session_id=SESSION, actor_id="dev-1", role="developer")
TASK = AgentTask(
    goal="Propose tests for account lockout after failed login attempts.",
    context=CONTEXT,
)


def fixture_pipeline():
    return build_retrieval_pipeline(
        load_documents_from_directory(CORPUS), corpus_version="fixture"
    )


def proposal_json(action: Action, arguments=None, evidence=(REQUIREMENT,)) -> str:
    return json.dumps(
        {
            "action": action.value,
            "arguments": {} if arguments is None else arguments,
            "rationale": "Grounded in the supplied context.",
            "evidence": [{"source_path": path} for path in evidence],
            "confidence": "high",
        }
    )


class RetrievalSensor:
    """Retrieves for the task goal, then builds the turn's context."""

    def __init__(self, pipeline) -> None:
        self.pipeline = pipeline

    def sense(self, task, state):
        return build_context(self.pipeline.retrieve(task.goal))


class ScriptedModelClient:
    """Stands in for ChatCompletionsClient with canned JSON responses."""

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = 0

    def generate(self, *, system_prompt, user_content):
        self.calls += 1
        return ModelCallResult(
            raw_text=self.responses[self.calls - 1],
            model="fixture-model",
            latency_ms=120,
            usage=TokenUsage(input_tokens=300, output_tokens=40, total_tokens=340),
            request_id=f"req-{self.calls}",
        )


class ModelPlanner:
    """One propose_action model call per turn, parsed by ProposalSet."""

    def __init__(self, client, system_prompt: str = "propose_action v1.2 prompt") -> None:
        self.client = client
        self.system_prompt = system_prompt

    def plan(self, task, context, state):
        result = self.client.generate(
            system_prompt=self.system_prompt,
            user_content=f"{task.goal}\n{context.text}",
        )
        return ProposalSet.model_validate_json(result.raw_text)


class ScriptedPlanner:
    def __init__(self, *proposals: ProposalSet) -> None:
        self.proposals = list(proposals)
        self.calls = 0

    def plan(self, task, context, state):
        self.calls += 1
        return self.proposals[self.calls - 1]


class FixedContextSensor:
    def __init__(self, context) -> None:
        self.context = context

    def sense(self, task, state):
        return self.context


class HaltAfter:
    def __init__(self, observations: int | None) -> None:
        self.observations = observations

    def evaluate(self, state):
        if self.observations is not None and state.iterations_completed >= self.observations:
            return StopReason.ITERATION_CAP
        return None


class RecordingTraceSink:
    def __init__(self) -> None:
        self.entries = []

    def record(self, entry) -> None:
        self.entries.append(entry)


class FailingTraceSink:
    def record(self, entry) -> None:
        raise OSError("trace store unavailable")


class FakeSearchTool:
    name = "search_repo"
    risk = ToolRisk.READ_ONLY
    allowed_roles = ("developer",)

    def __init__(self, output=None) -> None:
        self.output = {"matches": [SOURCE]} if output is None else output

    def validate_arguments(self, arguments):
        if "query" not in arguments:
            raise ValueError("query is required")
        return dict(arguments)

    def run(self, arguments, context):
        return self.output

    def validate_output(self, output):
        return dict(output)


class FakeRunTestsTool(FakeSearchTool):
    name = "run_tests"
    risk = ToolRisk.REQUIRES_APPROVAL

    def validate_arguments(self, arguments):
        return dict(arguments)


class PendingGate:
    def check(self, *, action, arguments, context):
        return ApprovalVerdict(ApprovalStatus.PENDING)


class FailingSink:
    def write(self, record) -> None:
        raise OSError("disk full")


def grounded_dependencies(*responses: str, tools=None, gate=None):
    pipeline = fixture_pipeline()
    return {
        "pipeline": pipeline,
        "sensor": RetrievalSensor(pipeline),
        "client": ScriptedModelClient(*responses),
        "dispatcher": ToolDispatcher(
            ToolRegistry([FakeSearchTool()] if tools is None else tools),
            approval_gate=gate,
        ),
        "stop": HaltAfter(None),
        "trace": RecordingTraceSink(),
    }


def build_plain_loop(deps) -> AgentLoop:
    return AgentLoop(
        sensor=deps["sensor"],
        planner=ModelPlanner(deps["client"]),
        dispatcher=deps["dispatcher"],
        stop_evaluator=deps["stop"],
        trace_sink=deps["trace"],
        clock=lambda: FIXED_NOW,
    )


def build_observed_loop(deps, recorder) -> AgentLoop:
    pipeline = ObservedRetrievalPipeline(deps["pipeline"], recorder)
    client = ObservedModelClient(
        deps["client"], recorder, prompt_id="propose_action", prompt_version="v1.2"
    )
    wrapped = instrument_loop(
        recorder,
        sensor=RetrievalSensor(pipeline),
        planner=ModelPlanner(client),
        dispatcher=deps["dispatcher"],
        trace_sink=deps["trace"],
        stop_evaluator=deps["stop"],
    )
    return AgentLoop(clock=lambda: FIXED_NOW, **wrapped.loop_kwargs())


def new_recorder(*sinks) -> ObservabilityRecorder:
    return ObservabilityRecorder(SESSION, sinks=sinks, clock=lambda: FIXED_NOW)


TWO_TURNS = (
    proposal_json(Action.SEARCH_REPO, {"query": "lockout threshold"}),
    proposal_json(Action.PROPOSE_TEST, {"title": "Lock after five failures"}),
)


def records_of(recorder, kind):
    return [r for r in recorder.records if r.kind is kind]


class BehaviourUnchangedTests(unittest.TestCase):
    def test_instrumented_run_matches_plain_run(self) -> None:
        plain_deps = grounded_dependencies(*TWO_TURNS)
        plain = build_plain_loop(plain_deps).run(TASK)

        observed_deps = grounded_dependencies(*TWO_TURNS)
        observed = build_observed_loop(observed_deps, new_recorder()).run(TASK)

        self.assertIs(plain.status, LoopStatus.COMPLETED)
        self.assertIs(observed.status, plain.status)
        self.assertEqual(observed.iterations, plain.iterations)
        self.assertEqual(observed.message, plain.message)
        self.assertEqual(observed.proposal, plain.proposal)
        self.assertEqual(
            [o.to_dict() for o in observed.state.history],
            [o.to_dict() for o in plain.state.history],
        )
        # Member 5's sink receives the identical TraceEntry sequence.
        self.assertEqual(observed_deps["trace"].entries, plain_deps["trace"].entries)

    def test_component_failure_keeps_loop_failure_and_records_type_only(self) -> None:
        class BrokenSensor:
            def sense(self, task, state):
                raise RuntimeError(f"index offline; token={SECRET}")

        recorder = new_recorder()
        wrapped = instrument_loop(
            recorder,
            sensor=BrokenSensor(),
            planner=ScriptedPlanner(),
            dispatcher=ToolDispatcher(ToolRegistry([FakeSearchTool()])),
            trace_sink=RecordingTraceSink(),
            stop_evaluator=HaltAfter(None),
        )
        result = AgentLoop(clock=lambda: FIXED_NOW, **wrapped.loop_kwargs()).run(TASK)

        self.assertIs(result.status, LoopStatus.FAILED)
        self.assertIs(result.failure, LoopFailure.SENSE_FAILED)
        (sense,) = records_of(recorder, StepKind.SENSE)
        self.assertFalse(sense.ok)
        self.assertEqual(sense.error_type, "RuntimeError")
        self.assertNotIn(SECRET, repr([r.to_dict() for r in recorder.records]))
        self.assertEqual(recorder.summary()["outcome"], "loop_failed")

    def test_trace_sink_failure_still_fails_closed(self) -> None:
        recorder = new_recorder()
        wrapped = instrument_loop(
            recorder,
            sensor=FixedContextSensor(build_context(fixture_pipeline().retrieve(TASK.goal))),
            planner=ScriptedPlanner(),
            dispatcher=ToolDispatcher(ToolRegistry([FakeSearchTool()])),
            trace_sink=FailingTraceSink(),
            stop_evaluator=HaltAfter(None),
        )
        result = AgentLoop(clock=lambda: FIXED_NOW, **wrapped.loop_kwargs()).run(TASK)

        self.assertIs(result.status, LoopStatus.FAILED)
        self.assertIs(result.failure, LoopFailure.TRACE_FAILED)
        (event,) = records_of(recorder, StepKind.LOOP_EVENT)
        self.assertFalse(event.ok)
        self.assertEqual(event.error_type, "OSError")
        self.assertEqual(event.attributes["event"], "loop_started")

    def test_telemetry_sink_failure_does_not_change_the_run(self) -> None:
        plain = build_plain_loop(grounded_dependencies(*TWO_TURNS)).run(TASK)
        recorder = new_recorder(FailingSink())
        observed = build_observed_loop(grounded_dependencies(*TWO_TURNS), recorder).run(TASK)

        self.assertIs(observed.status, plain.status)
        self.assertEqual(observed.proposal, plain.proposal)
        self.assertEqual(recorder.dropped_writes, len(recorder.records))
        self.assertGreater(recorder.dropped_writes, 0)


class RecordedEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = InMemoryStepSink()
        self.recorder = new_recorder(self.memory)
        self.result = build_observed_loop(
            grounded_dependencies(*TWO_TURNS), self.recorder
        ).run(TASK)

    def test_every_step_of_a_two_turn_run_is_recorded_in_order(self) -> None:
        self.assertIs(self.result.status, LoopStatus.COMPLETED)
        kinds = [r.kind.value for r in self.recorder.records]
        turn = ["retrieval", "sense", "loop_event", "model_call", "plan", "loop_event"]
        self.assertEqual(
            kinds,
            ["loop_event", "stop_check"]
            + turn
            + ["tool_call", "loop_event", "stop_check"]
            + turn
            + ["loop_event"],
        )
        self.assertEqual(self.memory.records, list(self.recorder.records))

    def test_model_call_records_model_prompt_tokens_and_latency(self) -> None:
        first = records_of(self.recorder, StepKind.MODEL_CALL)[0].attributes
        self.assertEqual(first["model"], "fixture-model")
        self.assertEqual(first["prompt_id"], "propose_action")
        self.assertEqual(first["prompt_version"], "v1.2")
        self.assertEqual(len(first["prompt_sha256"]), 16)
        self.assertEqual(first["total_tokens"], 340)
        self.assertEqual(first["provider_latency_ms"], 120)
        self.assertEqual(first["request_id"], "req-1")

    def test_plan_records_action_and_traceable_evidence(self) -> None:
        plans = [r.attributes for r in records_of(self.recorder, StepKind.PLAN)]
        self.assertEqual([p["action"] for p in plans], ["search_repo", "propose_test"])
        self.assertEqual(plans[0]["argument_keys"], ("query",))
        self.assertEqual(plans[0]["evidence_traceable"], (REQUIREMENT,))
        self.assertEqual(plans[0]["evidence_untraceable"], 0)

    def test_retrieval_records_sources_scores_and_corpus(self) -> None:
        retrieval = records_of(self.recorder, StepKind.RETRIEVAL)[0].attributes
        self.assertFalse(retrieval["not_in_corpus"])
        self.assertEqual(retrieval["source_paths"], (TEST_LOG, REQUIREMENT, SOURCE))
        self.assertEqual(retrieval["corpus_version"], "fixture")
        self.assertEqual(retrieval["chunks_returned"], len(retrieval["chunks"]))
        self.assertGreater(retrieval["chunks"][0]["score"], 0)
        sense = records_of(self.recorder, StepKind.SENSE)[0].attributes
        self.assertEqual(sense["allowed_sources"], retrieval["source_paths"])
        self.assertEqual(sense["iteration"], 1)

    def test_tool_call_records_name_status_and_output_size(self) -> None:
        (tool,) = records_of(self.recorder, StepKind.TOOL_CALL)
        self.assertTrue(tool.ok)
        self.assertEqual(tool.attributes["tool"], "search_repo")
        self.assertEqual(tool.attributes["argument_keys"], ("query",))
        self.assertEqual(tool.attributes["status"], "executed")
        self.assertIsNone(tool.attributes["code"])
        self.assertEqual(tool.attributes["output_keys"], ("matches",))
        self.assertEqual(
            tool.attributes["output_bytes"],
            len(json.dumps({"matches": [SOURCE]}, separators=(",", ":"))),
        )

    def test_summary_answers_the_week7_questions(self) -> None:
        summary = self.recorder.summary()
        self.assertEqual(summary["outcome"], "loop_completed")
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["model"]["calls"], 2)
        self.assertEqual(summary["model"]["total_tokens"], 680)
        self.assertEqual(summary["model"]["planned_actions"], ["search_repo", "propose_test"])
        self.assertEqual(summary["retrieval"]["sources"], [TEST_LOG, REQUIREMENT, SOURCE])
        self.assertEqual(summary["tools"]["by_tool"], {"search_repo": 1})
        for kind in ("retrieval", "sense", "model_call", "plan", "tool_call", "stop_check"):
            self.assertIn(kind, summary["by_kind"])
            self.assertGreaterEqual(summary["by_kind"][kind]["total_ms"], 0)


class SafetyEvidenceTests(unittest.TestCase):
    def test_fabricated_citation_is_counted_not_copied(self) -> None:
        recorder = new_recorder()
        planned = ProposalSet(
            action=Action.PROPOSE_TEST,
            arguments={"title": "t"},
            rationale="r",
            evidence=(EvidenceRef(source_path=FABRICATED),),
            confidence=Confidence.HIGH,
        )
        wrapped = instrument_loop(
            recorder,
            sensor=FixedContextSensor(build_context(fixture_pipeline().retrieve(TASK.goal))),
            planner=ScriptedPlanner(planned),
            dispatcher=ToolDispatcher(ToolRegistry([FakeSearchTool()])),
            trace_sink=RecordingTraceSink(),
            stop_evaluator=HaltAfter(1),
        )
        result = AgentLoop(clock=lambda: FIXED_NOW, **wrapped.loop_kwargs()).run(TASK)

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertIs(result.state.history[0].kind, ObservationKind.CITATION_REJECTED)
        (plan,) = records_of(recorder, StepKind.PLAN)
        self.assertEqual(plan.attributes["evidence_untraceable"], 1)
        self.assertEqual(plan.attributes["evidence_traceable"], ())
        self.assertNotIn(FABRICATED, repr([r.to_dict() for r in recorder.records]))
        stops = records_of(recorder, StepKind.STOP_CHECK)
        self.assertEqual(stops[-1].attributes["decision"], "iteration_cap")
        self.assertEqual(recorder.summary()["outcome"], "loop_halted")

    def test_secret_values_never_reach_the_telemetry_file(self) -> None:
        responses = (
            proposal_json(Action.SEARCH_REPO, {"query": SECRET}),
            proposal_json(Action.PROPOSE_TEST, {"title": SECRET}),
        )
        deps = grounded_dependencies(
            *responses, tools=[FakeSearchTool(output={"content": SECRET})]
        )
        with tempfile.TemporaryDirectory() as tmp:
            sink = JsonlStepSink(tmp)
            recorder = new_recorder(sink)
            pipeline = ObservedRetrievalPipeline(deps["pipeline"], recorder)
            client = ObservedModelClient(deps["client"], recorder)
            wrapped = instrument_loop(
                recorder,
                sensor=RetrievalSensor(pipeline),
                planner=ModelPlanner(client, system_prompt=f"prompt {SECRET}"),
                dispatcher=deps["dispatcher"],
                trace_sink=deps["trace"],
                stop_evaluator=deps["stop"],
            )
            secret_task = AgentTask(goal=f"{TASK.goal} {SECRET}", context=CONTEXT)
            result = AgentLoop(clock=lambda: FIXED_NOW, **wrapped.loop_kwargs()).run(
                secret_task
            )

            self.assertIs(result.status, LoopStatus.COMPLETED)
            text = sink.path_for(SESSION).read_text(encoding="utf-8")
        self.assertIn('"tool": "search_repo"', text)
        self.assertNotIn(SECRET, text)

    def test_approval_pending_tool_call_is_recorded_as_paused(self) -> None:
        deps = grounded_dependencies(
            proposal_json(Action.RUN_TESTS, {"test_ids": ["tests/test_login.py::t"]}),
            tools=[FakeRunTestsTool()],
            gate=PendingGate(),
        )
        recorder = new_recorder()
        result = build_observed_loop(deps, recorder).run(TASK)

        self.assertIs(result.status, LoopStatus.AWAITING_APPROVAL)
        (tool,) = records_of(recorder, StepKind.TOOL_CALL)
        self.assertEqual(tool.attributes["tool"], "run_tests")
        self.assertEqual(tool.attributes["status"], "awaiting_approval")
        self.assertEqual(tool.attributes["code"], "approval_pending")
        self.assertIsNone(tool.attributes["output_bytes"])
        self.assertEqual(recorder.summary()["outcome"], "loop_paused")


class TeamIntegrationTests(unittest.TestCase):
    def test_member5_run_logger_still_receives_every_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_logger = RunLogger(tmp)
            deps = grounded_dependencies(*TWO_TURNS)
            deps["trace"] = run_logger
            recorder = new_recorder()
            result = build_observed_loop(deps, recorder).run(TASK)

            (row,) = load_index(tmp)
            entries = load_run(Path(tmp) / row["file"])
        self.assertIs(result.status, LoopStatus.COMPLETED)
        self.assertEqual(row["outcome"], "loop_completed")
        self.assertEqual(
            [entry["action"] for entry in entries],
            [r.attributes["event"] for r in records_of(recorder, StepKind.LOOP_EVENT)],
        )

    def test_runner_accepts_an_instrumented_dispatcher(self) -> None:
        contract = AgentTaskContract(
            goal=TASK.goal,
            tools=("search_repo",),
            max_iterations=3,
            wall_clock_budget_seconds=30.0,
        )
        recorder = new_recorder()
        deps = grounded_dependencies(*TWO_TURNS)
        wrapped = instrument_loop(
            recorder,
            sensor=deps["sensor"],
            planner=ModelPlanner(deps["client"]),
            dispatcher=deps["dispatcher"],
            trace_sink=deps["trace"],
        )
        self.assertIsInstance(wrapped.dispatcher, ObservedDispatcher)
        self.assertIs(wrapped.dispatcher.registry, deps["dispatcher"].registry)

        session = build_agent_session(
            contract,
            session_id=SESSION,
            actor_id="dev-1",
            role="developer",
            **wrapped.loop_kwargs(),
        )
        result = session.run()

        self.assertIs(result.status, LoopStatus.COMPLETED)
        self.assertEqual(len(records_of(recorder, StepKind.TOOL_CALL)), 1)
        self.assertEqual(records_of(recorder, StepKind.STOP_CHECK), [])

    def test_wrappers_reject_missing_components(self) -> None:
        recorder = new_recorder()
        with self.assertRaises(ValueError):
            ObservedModelClient(object(), recorder)
        with self.assertRaises(ValueError):
            ObservedDispatcher(ToolDispatcher(ToolRegistry([])), object())
        with self.assertRaises(ValueError):
            ObservedModelClient(ScriptedModelClient(), recorder, prompt_version=" ")


if __name__ == "__main__":
    unittest.main()
