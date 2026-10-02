"""Week 5 stop-condition tests and execution-trace evidence (Member 4,
Quality/Security Lead).

Deliverable per the task allocation plan: "Record three full runs of the
agent, including one where it fails and recovers, and write a test that
checks the stop conditions actually work." -> tests/test_stop_conditions.py
plus three execution traces under evidence/traces/.

REAL POLICY, REAL LOOP
-----------------------
This file originally shipped its own stand-in StopConditionPolicy, because
src/agent/stop_conditions.py (Member 1's Week 5 deliverable) did not exist
yet when this suite was first written. It has since landed, and its own
docstring says it was deliberately built as "a behavioural drop-in" for the
stand-in this file used to define -- same constructor shape, same
precedence order, same interpretation of "repeated call" and "no new
information." This file now imports and tests the real
agent.stop_conditions.StopConditionPolicy directly; nothing below is
simulated.

Four conditions, named in US-9 and the AI engineering design notes:

  - ITERATION_CAP            a hard maximum number of completed turns.
  - WALL_CLOCK_BUDGET        a maximum elapsed wall-clock time for the run.
  - REPEATED_CALL_DETECTED   the same action+arguments requested again.
  - NO_NEW_INFORMATION       a tool executed twice in a row returning the
                              exact same output.

Every test below runs the real policy through the REAL agent.AgentLoop
(Member 2's Week 5 deliverable). tests/integration/test_agent_loop.py
already covers the loop's own mechanics against an injected stop evaluator
in the abstract (its docstring says explicitly: "these checks ... do not
replace Member 4's stop-condition or execution-trace tests"); this file is
that replacement -- it tests whether the real stop POLICY actually decides
correctly, not just whether the loop obeys whatever an evaluator says.
tests/test_stop_conditions_unit.py (Member 1) separately unit-tests the
policy's own internals; this file additionally wires it into the real loop
and generates the three required execution traces, which is specifically
this week's Member 4 deliverable.

Usage:
    PYTHONPATH=src python3 tests/test_stop_conditions.py

Also runnable as part of the automated suite:
    PYTHONPATH=src python3 -m unittest tests.test_stop_conditions -v
"""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent import (  # noqa: E402
    AgentLoop,
    AgentTask,
    LoopState,
    LoopStatus,
    Observation,
    ObservationKind,
    PlannedAction,
)
from agent.stop_conditions import StopConditionPolicy  # noqa: E402
from models.types import (  # noqa: E402
    Action,
    Confidence,
    EvidenceRef,
    ProposalSet,
    StopReason,
    TraceEntry,
)
from orchestrator import (  # noqa: E402
    ApprovalStatus,
    ApprovalVerdict,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRisk,
)
from rag import AssembledContext  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "evidence" / "traces"
SOURCE = "tests/fixtures/member2/corpus/src/login_service.py"


# ---------------------------------------------------------------------------
# Minimal, self-contained loop fixtures. A different, independent set from
# tests/integration/test_agent_loop.py's Harness, so this file can run and
# be understood without that one -- but the same established conventions
# (scripted sensor/planner, real ToolDispatcher with a fake tool).
# ---------------------------------------------------------------------------

CONTEXT = ExecutionContext(session_id="session-1", actor_id="dev-1", role="developer")


def grounded_context() -> AssembledContext:
    return AssembledContext(
        text="<evidence>fixture</evidence>",
        chunks_used=1,
        chunks_dropped=0,
        not_in_corpus=False,
        allowed_source_paths=frozenset({SOURCE}),
    )


def proposal(action: Action, arguments: dict[str, Any] | None = None) -> ProposalSet:
    return ProposalSet(
        action=action,
        arguments={} if arguments is None else arguments,
        rationale="Grounded in the supplied context.",
        evidence=(EvidenceRef(source_path=SOURCE),),
        confidence=Confidence.HIGH,
    )


def search(query: str = "lockout") -> ProposalSet:
    return proposal(Action.SEARCH_REPO, {"query": query})


def propose_test() -> ProposalSet:
    return proposal(Action.PROPOSE_TEST, {"title": "Lock account after five failures"})


class ScriptedSensor:
    def sense(self, task, state):
        return grounded_context()


class ScriptedPlanner:
    """Returns one proposal per call, in order; raises if over-called."""

    def __init__(self, proposals: list[ProposalSet]) -> None:
        self.proposals = list(proposals)
        self.calls = 0

    def plan(self, task, context, state):
        if self.calls >= len(self.proposals):
            raise AssertionError("Planner called more often than scripted.")
        result = self.proposals[self.calls]
        self.calls += 1
        return result


class FakeTool:
    """Minimal Member 3 tool stand-in: succeeds, or fails a fixed number of
    times before succeeding, to script a genuine failure-then-recovery."""

    name = "search_repo"
    risk = ToolRisk.READ_ONLY
    allowed_roles = ("developer",)

    def __init__(self, *, fail_times: int = 0, output: dict | None = None) -> None:
        self.fail_times = fail_times
        self.output = output or {"matches": [SOURCE]}
        self.calls = 0

    def validate_arguments(self, arguments):
        if "query" not in arguments:
            raise ValueError("missing 'query'")
        return dict(arguments)

    def run(self, arguments, context):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient search backend error")
        return self.output

    def validate_output(self, output):
        return dict(output)


class AutoApproveGate:
    def check(self, *, action, arguments, context):
        return ApprovalVerdict(ApprovalStatus.APPROVED)


class RecordingTraceSink:
    def __init__(self) -> None:
        self.entries: list[TraceEntry] = []

    def record(self, entry: TraceEntry) -> None:
        self.entries.append(entry)

    @property
    def actions(self) -> list[str]:
        return [entry.action for entry in self.entries]


class FakeClock:
    """Shared, advanceable clock for the loop and the policy under test."""

    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def build_loop(
    *,
    planner: ScriptedPlanner,
    tool: FakeTool,
    policy: StopConditionPolicy,
    clock: Callable[[], datetime],
    trace: RecordingTraceSink,
) -> AgentLoop:
    dispatcher = ToolDispatcher(ToolRegistry([tool]), approval_gate=AutoApproveGate())
    return AgentLoop(
        sensor=ScriptedSensor(),
        planner=planner,
        dispatcher=dispatcher,
        stop_evaluator=policy,
        trace_sink=trace,
        clock=clock,
    )


TASK = AgentTask(goal="Propose tests for the login lockout requirement.", context=CONTEXT)


# ---------------------------------------------------------------------------
# Policy logic in isolation.
# ---------------------------------------------------------------------------


def _executed(iteration: int, action: Action, arguments: dict, output: dict) -> Observation:
    return Observation(
        iteration=iteration,
        proposal=PlannedAction.from_proposal(proposal(action, arguments)),
        kind=ObservationKind.TOOL_EXECUTED,
        message="The tool executed successfully.",
        output=output,
    )


class PolicyLogicTests(unittest.TestCase):
    def test_allows_continuation_with_no_history(self) -> None:
        policy = StopConditionPolicy(max_iterations=5, wall_clock_budget_seconds=60)
        state = LoopState(session_id="s1")

        self.assertIsNone(policy.evaluate(state))

    def test_iteration_cap_halts_exactly_at_the_configured_maximum(self) -> None:
        policy = StopConditionPolicy(max_iterations=2, wall_clock_budget_seconds=600)
        one = LoopState(session_id="s1", history=(_executed(1, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}),))
        two = LoopState(
            session_id="s1",
            history=(
                _executed(1, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}),
                _executed(2, Action.SEARCH_REPO, {"query": "b"}, {"matches": ["y"]}),
            ),
        )

        self.assertIsNone(policy.evaluate(one))
        self.assertEqual(policy.evaluate(two), StopReason.ITERATION_CAP)

    def test_wall_clock_budget_halts_once_elapsed_time_exceeds_budget(self) -> None:
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        policy = StopConditionPolicy(
            max_iterations=1000, wall_clock_budget_seconds=30, clock=clock
        )
        state = LoopState(session_id="s1")

        self.assertIsNone(policy.evaluate(state))  # starts the clock, elapsed=0
        clock.advance(10)
        self.assertIsNone(policy.evaluate(state))
        clock.advance(25)
        self.assertEqual(policy.evaluate(state), StopReason.WALL_CLOCK_BUDGET)

    def test_identical_repeated_call_is_detected(self) -> None:
        policy = StopConditionPolicy(max_iterations=1000, wall_clock_budget_seconds=600)
        state = LoopState(
            session_id="s1",
            history=(
                _executed(1, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}),
                _executed(2, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}),
            ),
        )

        self.assertEqual(policy.evaluate(state), StopReason.REPEATED_CALL_DETECTED)

    def test_different_arguments_are_not_a_repeated_call(self) -> None:
        policy = StopConditionPolicy(max_iterations=1000, wall_clock_budget_seconds=600)
        state = LoopState(
            session_id="s1",
            history=(
                _executed(1, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}),
                _executed(2, Action.SEARCH_REPO, {"query": "b"}, {"matches": ["y"]}),
            ),
        )

        self.assertIsNone(policy.evaluate(state))

    def test_identical_output_twice_is_no_new_information(self) -> None:
        policy = StopConditionPolicy(max_iterations=1000, wall_clock_budget_seconds=600)
        state = LoopState(
            session_id="s1",
            history=(
                _executed(1, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}),
                _executed(2, Action.SEARCH_REPO, {"query": "b"}, {"matches": ["x"]}),
            ),
        )

        self.assertEqual(policy.evaluate(state), StopReason.NO_NEW_INFORMATION)

    def test_changed_output_is_not_flagged_as_no_new_information(self) -> None:
        policy = StopConditionPolicy(max_iterations=1000, wall_clock_budget_seconds=600)
        state = LoopState(
            session_id="s1",
            history=(
                _executed(1, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}),
                _executed(2, Action.SEARCH_REPO, {"query": "b"}, {"matches": ["x", "y"]}),
            ),
        )

        self.assertIsNone(policy.evaluate(state))

    def test_a_rejected_or_errored_observation_does_not_count_as_no_new_information(self) -> None:
        policy = StopConditionPolicy(max_iterations=1000, wall_clock_budget_seconds=600)
        errored = Observation(
            iteration=2,
            proposal=PlannedAction.from_proposal(search("b")),
            kind=ObservationKind.TOOL_ERROR,
            message="The tool could not complete the request.",
            output=None,
        )
        state = LoopState(
            session_id="s1",
            history=(_executed(1, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}), errored),
        )

        self.assertIsNone(policy.evaluate(state))

    def test_iteration_cap_takes_precedence_over_other_conditions(self) -> None:
        # Both the iteration cap and a repeated call apply here; the
        # documented, deterministic precedence is ITERATION_CAP first.
        policy = StopConditionPolicy(max_iterations=2, wall_clock_budget_seconds=600)
        state = LoopState(
            session_id="s1",
            history=(
                _executed(1, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}),
                _executed(2, Action.SEARCH_REPO, {"query": "a"}, {"matches": ["x"]}),
            ),
        )

        self.assertEqual(policy.evaluate(state), StopReason.ITERATION_CAP)

    def test_rejects_non_positive_configuration(self) -> None:
        with self.assertRaises(ValueError):
            StopConditionPolicy(max_iterations=0, wall_clock_budget_seconds=60)
        with self.assertRaises(ValueError):
            StopConditionPolicy(max_iterations=5, wall_clock_budget_seconds=0)


# ---------------------------------------------------------------------------
# The policy wired into the real AgentLoop.
# ---------------------------------------------------------------------------


class StopConditionIntegrationTests(unittest.TestCase):
    def test_iteration_cap_halts_the_real_loop_and_appears_in_the_trace(self) -> None:
        """US-9's own acceptance criterion: the loop halts automatically at
        the configured maximum, and the halt event appears in the trace."""

        tool = FakeTool()
        planner = ScriptedPlanner([search("a"), search("b"), search("c")])
        policy = StopConditionPolicy(max_iterations=2, wall_clock_budget_seconds=600)
        trace = RecordingTraceSink()
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        loop = build_loop(planner=planner, tool=tool, policy=policy, clock=clock, trace=trace)

        result = loop.run(TASK)

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertIsNotNone(result.halt)
        self.assertIs(result.halt.reason, StopReason.ITERATION_CAP)
        self.assertEqual(result.halt.iteration_count, 2)
        self.assertEqual(tool.calls, 2)  # the third scripted call was never reached
        self.assertIn("loop_halted", trace.actions)
        halted_entry = trace.entries[-1]
        self.assertIn("reason=iteration_cap", halted_entry.detail)

    def test_repeated_call_detected_halts_the_real_loop(self) -> None:
        tool = FakeTool()
        planner = ScriptedPlanner([search("a"), search("a"), search("a")])
        policy = StopConditionPolicy(max_iterations=1000, wall_clock_budget_seconds=600)
        trace = RecordingTraceSink()
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        loop = build_loop(planner=planner, tool=tool, policy=policy, clock=clock, trace=trace)

        result = loop.run(TASK)

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertIs(result.halt.reason, StopReason.REPEATED_CALL_DETECTED)
        self.assertEqual(tool.calls, 2)

    def test_no_new_information_halts_the_real_loop(self) -> None:
        tool = FakeTool(output={"matches": [SOURCE]})
        planner = ScriptedPlanner([search("a"), search("b"), search("c")])
        policy = StopConditionPolicy(max_iterations=1000, wall_clock_budget_seconds=600)
        trace = RecordingTraceSink()
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        loop = build_loop(planner=planner, tool=tool, policy=policy, clock=clock, trace=trace)

        result = loop.run(TASK)

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertIs(result.halt.reason, StopReason.NO_NEW_INFORMATION)
        self.assertEqual(tool.calls, 2)

    def test_wall_clock_budget_halts_the_real_loop(self) -> None:
        tool = FakeTool()
        planner = ScriptedPlanner([search("a"), search("b")])
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))

        class AdvancingTool(FakeTool):
            def run(self, arguments, context):
                clock.advance(20)
                return super().run(arguments, context)

        tool = AdvancingTool(output={"matches": [SOURCE]})
        policy = StopConditionPolicy(
            max_iterations=1000, wall_clock_budget_seconds=15, clock=clock
        )
        trace = RecordingTraceSink()
        loop = build_loop(planner=planner, tool=tool, policy=policy, clock=clock, trace=trace)

        result = loop.run(TASK)

        self.assertIs(result.status, LoopStatus.HALTED)
        self.assertIs(result.halt.reason, StopReason.WALL_CLOCK_BUDGET)
        self.assertEqual(tool.calls, 1)

    def test_loop_completes_normally_when_no_stop_condition_fires(self) -> None:
        tool = FakeTool()
        planner = ScriptedPlanner([search("a"), propose_test()])
        policy = StopConditionPolicy(max_iterations=1000, wall_clock_budget_seconds=600)
        trace = RecordingTraceSink()
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        loop = build_loop(planner=planner, tool=tool, policy=policy, clock=clock, trace=trace)

        result = loop.run(TASK)

        self.assertIs(result.status, LoopStatus.COMPLETED)
        self.assertNotIn("loop_halted", trace.actions)


# ---------------------------------------------------------------------------
# Three execution traces (evidence/traces/), generated through the real loop.
# ---------------------------------------------------------------------------


def _serialize_entry(entry: TraceEntry) -> dict[str, Any]:
    return {
        "session_id": entry.session_id,
        "actor": entry.actor.value,
        "action": entry.action,
        "detail": entry.detail,
        "timestamp": entry.timestamp.isoformat(),
        "tool_invocation": None
        if entry.tool_invocation is None
        else {
            "tool_name": entry.tool_invocation.tool_name,
            "input": entry.tool_invocation.input,
            "output": entry.tool_invocation.output,
            "called_at": entry.tool_invocation.called_at.isoformat(),
        },
    }


def _serialize_result(run_name: str, result) -> dict[str, Any]:
    return {
        "run": run_name,
        "task": {"goal": result.task.goal, "session_id": result.task.context.session_id},
        "result": {
            "status": result.status.value,
            "iterations": result.iterations,
            "message": result.message,
            "halt": None
            if result.halt is None
            else {
                "reason": result.halt.reason.value,
                "iteration_count": result.halt.iteration_count,
                "halted_at": result.halt.halted_at.isoformat(),
            },
            "failure": result.failure.value if result.failure else None,
            "final_proposal": None if result.proposal is None else result.proposal.to_dict(),
        },
    }


@dataclass
class GeneratedTrace:
    name: str
    path: Path
    payload: dict[str, Any] = field(repr=False)


def _run_completed() -> tuple[Any, RecordingTraceSink]:
    """Run 1: a clean, two-turn session that completes normally."""

    tool = FakeTool(output={"matches": [SOURCE]})
    planner = ScriptedPlanner([search("account lockout"), propose_test()])
    policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=600)
    trace = RecordingTraceSink()
    clock = FakeClock(datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc))
    loop = build_loop(planner=planner, tool=tool, policy=policy, clock=clock, trace=trace)
    return loop.run(TASK), trace


def _run_failure_then_recovery() -> tuple[Any, RecordingTraceSink]:
    """Run 2: the tool fails once, then the agent retries and recovers."""

    tool = FakeTool(fail_times=1, output={"matches": [SOURCE]})
    planner = ScriptedPlanner(
        [search("account lockout"), search("account lockout retry"), propose_test()]
    )
    policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=600)
    trace = RecordingTraceSink()
    clock = FakeClock(datetime(2026, 10, 2, 9, 5, tzinfo=timezone.utc))
    loop = build_loop(planner=planner, tool=tool, policy=policy, clock=clock, trace=trace)
    return loop.run(TASK), trace


def _run_stop_condition_halt() -> tuple[Any, RecordingTraceSink]:
    """Run 3: the agent repeats the identical call and the stop policy halts
    it -- the direct demonstration that a stop condition actually works."""

    tool = FakeTool(output={"matches": [SOURCE]})
    planner = ScriptedPlanner([search("account lockout")] * 5)
    policy = StopConditionPolicy(max_iterations=10, wall_clock_budget_seconds=600)
    trace = RecordingTraceSink()
    clock = FakeClock(datetime(2026, 10, 2, 9, 10, tzinfo=timezone.utc))
    loop = build_loop(planner=planner, tool=tool, policy=policy, clock=clock, trace=trace)
    return loop.run(TASK), trace


RUNS: dict[str, Callable[[], tuple[Any, RecordingTraceSink]]] = {
    "week5-run-1-completed": _run_completed,
    "week5-run-2-failure-recovery": _run_failure_then_recovery,
    "week5-run-3-stop-condition-halt": _run_stop_condition_halt,
}


def generate_traces(output_dir: Path = EVIDENCE_DIR) -> list[GeneratedTrace]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    for name, run in RUNS.items():
        result, trace = run()
        payload = _serialize_result(name, result)
        payload["trace"] = [_serialize_entry(entry) for entry in trace.entries]
        path = output_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        generated.append(GeneratedTrace(name=name, path=path, payload=payload))
    return generated


class ExecutionTraceGenerationTests(unittest.TestCase):
    """Regenerates the three evidence traces and checks each is exactly the
    scenario it claims to be -- so the evidence files are reproducible, not
    hand-edited."""

    def test_three_traces_are_generated_with_the_right_outcomes(self) -> None:
        traces = generate_traces()
        by_name = {t.name: t for t in traces}

        self.assertEqual(len(traces), 3)
        for trace in traces:
            self.assertTrue(trace.path.is_file())
            # Round-trip through JSON to prove the file itself is valid,
            # not just the in-memory payload.
            json.loads(trace.path.read_text(encoding="utf-8"))

        completed = by_name["week5-run-1-completed"].payload["result"]
        self.assertEqual(completed["status"], "completed")
        self.assertIsNone(completed["halt"])

        recovery = by_name["week5-run-2-failure-recovery"].payload
        self.assertEqual(recovery["result"]["status"], "completed")
        kinds = [entry["action"] for entry in recovery["trace"]]
        self.assertIn("tool_dispatched", kinds)
        tool_events = [
            entry for entry in recovery["trace"] if entry["action"] == "tool_dispatched"
        ]
        self.assertEqual(tool_events[0]["tool_invocation"]["output"]["kind"], "tool_error")
        self.assertEqual(tool_events[1]["tool_invocation"]["output"]["kind"], "tool_executed")

        halted = by_name["week5-run-3-stop-condition-halt"].payload["result"]
        self.assertEqual(halted["status"], "halted")
        self.assertEqual(halted["halt"]["reason"], "repeated_call_detected")


def main() -> int:
    traces = generate_traces()
    for trace in traces:
        status = trace.payload["result"]["status"]
        print(f"{trace.name}: status={status} -> {trace.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
