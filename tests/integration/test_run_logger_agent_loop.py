"""Member 5's run logger wired into Member 2's real agent loop.

The loop, citation validator and ToolDispatcher are real; the sensor,
planner, stop evaluator and tool are deterministic fakes, except in the last
test, which also uses Member 5's real JSONApprovalGate.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent import AgentLoop, AgentTask, LoopEvent, LoopFailure, LoopStatus
from models.types import Action, Confidence, EvidenceRef, ProposalSet, StopReason
from observability import RunLogger, load_index, load_run
from observability import run_logger as run_logger_module
from orchestrator import (
    ApprovalStatus,
    ApprovalVerdict,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRisk,
)
from orchestrator.approval_gate import AuditLogger, JSONApprovalGate, JSONApprovalStore
from rag import AssembledContext

SOURCE = "code/config_loader.py"
FABRICATED = "pricing/discount_table.md"
FIXED_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
CONTEXT = ExecutionContext(session_id="session-1", actor_id="dev-1", role="developer")


def proposal(action: Action, arguments=None, evidence=(SOURCE,)) -> ProposalSet:
    return ProposalSet(
        action=action,
        arguments={} if arguments is None else arguments,
        rationale="Grounded in the supplied context.",
        evidence=tuple(EvidenceRef(source_path=path) for path in evidence),
        confidence=Confidence.HIGH,
    )


class FixedSensor:
    def sense(self, task, state):
        return AssembledContext(
            text="<evidence>fixture</evidence>",
            chunks_used=1,
            chunks_dropped=0,
            not_in_corpus=False,
            allowed_source_paths=frozenset({SOURCE}),
        )


class ScriptedPlanner:
    def __init__(self, *proposals) -> None:
        self.proposals = list(proposals)

    def plan(self, task, context, state):
        if not self.proposals:
            raise RuntimeError("Planner ran out of scripted proposals.")
        return self.proposals.pop(0)


class IterationCap:
    def __init__(self, cap: int | None = None) -> None:
        self.cap = cap

    def evaluate(self, state):
        if self.cap is not None and state.iterations_completed >= self.cap:
            return StopReason.ITERATION_CAP
        return None


class FakeTool:
    def __init__(self, name="search_repo", risk=ToolRisk.READ_ONLY) -> None:
        self.name = name
        self.risk = risk
        self.allowed_roles = ("developer",)

    def validate_arguments(self, arguments):
        if "query" not in arguments:
            raise ValueError("query is required")
        return dict(arguments)

    def run(self, arguments, context):
        return {"matches": [SOURCE]}

    def validate_output(self, output):
        return dict(output)


class SequencedGate:
    def __init__(self, *statuses: ApprovalStatus) -> None:
        self.statuses = list(statuses)

    def check(self, *, action, arguments, context):
        return ApprovalVerdict(self.statuses.pop(0))


class RunLoggerAgentLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="run_logger_loop_"))
        self.logger = RunLogger(self.directory)

    def tearDown(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def loop(self, planner, *, tool=None, gate=None, cap=None) -> AgentLoop:
        return AgentLoop(
            sensor=FixedSensor(),
            planner=planner,
            dispatcher=ToolDispatcher(
                ToolRegistry([tool or FakeTool()]), approval_gate=gate
            ),
            stop_evaluator=IterationCap(cap),
            trace_sink=self.logger,
            clock=lambda: FIXED_NOW,
        )

    def task(self) -> AgentTask:
        return AgentTask(goal="Propose tests for configuration loading.", context=CONTEXT)

    def run_files(self) -> list[Path]:
        return sorted(
            path for path in self.directory.glob("*.jsonl") if path.name != "index.jsonl"
        )

    def test_lifecycle_constants_match_the_loop_events(self) -> None:
        values = {event.value for event in LoopEvent}
        self.assertLessEqual(run_logger_module.RUN_OPENING_EVENTS, values)
        self.assertLessEqual(run_logger_module.RUN_TERMINAL_EVENTS, values)
        self.assertEqual(
            run_logger_module.RUN_OPENING_EVENTS,
            {LoopEvent.STARTED.value, LoopEvent.RESUMED.value},
        )
        self.assertEqual(
            run_logger_module.RUN_TERMINAL_EVENTS,
            {
                LoopEvent.COMPLETED.value,
                LoopEvent.PAUSED.value,
                LoopEvent.HALTED.value,
                LoopEvent.FAILED.value,
            },
        )

    def test_completed_run_is_saved_with_its_tool_call(self) -> None:
        result = self.loop(
            ScriptedPlanner(
                proposal(Action.SEARCH_REPO, {"query": "distinctive-query-value"}),
                proposal(Action.PROPOSE_TEST, {"title": "Missing key raises"}),
            )
        ).run(self.task())

        self.assertIs(result.status, LoopStatus.COMPLETED)
        lines = load_run(self.run_files()[0])
        self.assertEqual(
            [line["action"] for line in lines],
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
        self.assertEqual(lines[3]["tool_invocation"]["tool_name"], "search_repo")
        # The loop's metadata-only contract survives persistence.
        self.assertEqual(
            lines[3]["tool_invocation"]["input"], {"argument_keys": ["query"]}
        )
        raw = self.run_files()[0].read_text(encoding="utf-8")
        self.assertNotIn("distinctive-query-value", raw)
        summary = load_index(self.directory)[0]
        self.assertEqual(summary["outcome"], "loop_completed")
        self.assertEqual(summary["tool_calls"], 1)
        self.assertEqual(summary["ai_decisions"], 2)

    def test_failure_and_recovery_are_both_in_one_run_file(self) -> None:
        result = self.loop(
            ScriptedPlanner(
                proposal(Action.PROPOSE_TEST, {"title": "x"}, evidence=(FABRICATED,)),
                proposal(Action.SEARCH_REPO, {}),
                proposal(Action.PROPOSE_TEST, {"title": "Missing key raises"}),
            )
        ).run(self.task())

        self.assertIs(result.status, LoopStatus.COMPLETED)
        actions = [line["action"] for line in load_run(self.run_files()[0])]
        self.assertIn("citations_rejected", actions)
        self.assertIn("tool_dispatched", actions)
        self.assertEqual(actions[-1], "loop_completed")
        self.assertNotIn(FABRICATED, self.run_files()[0].read_text(encoding="utf-8"))

    def test_halted_and_failed_runs_are_saved_and_indexed(self) -> None:
        halted = self.loop(
            ScriptedPlanner(*[proposal(Action.SEARCH_REPO, {"query": "q"})] * 3),
            cap=2,
        ).run(self.task())
        failed = self.loop(ScriptedPlanner()).run(self.task())

        self.assertIs(halted.status, LoopStatus.HALTED)
        self.assertIs(failed.status, LoopStatus.FAILED)
        self.assertEqual(len(self.run_files()), 2)
        outcomes = [row["outcome"] for row in load_index(self.directory)]
        self.assertEqual(outcomes, ["loop_halted", "loop_failed"])
        self.assertIn("reason=iteration_cap", load_index(self.directory)[0]["detail"])

    def test_approval_pause_and_resume_stay_in_one_file(self) -> None:
        loop = self.loop(
            ScriptedPlanner(
                proposal(Action.RUN_TESTS, {"query": "unit"}),
                proposal(Action.PROPOSE_TEST, {"title": "Missing key raises"}),
            ),
            tool=FakeTool("run_tests", ToolRisk.REQUIRES_APPROVAL),
            gate=SequencedGate(ApprovalStatus.PENDING),
        )

        paused = loop.run(self.task())
        self.assertIs(paused.status, LoopStatus.AWAITING_APPROVAL)
        finished = loop.resume(paused)
        self.assertIs(finished.status, LoopStatus.COMPLETED)

        files = self.run_files()
        self.assertEqual(len(files), 1)
        actions = [line["action"] for line in load_run(files[0])]
        self.assertIn("loop_paused", actions)
        self.assertIn("loop_resumed", actions)
        self.assertEqual(actions[-1], "loop_completed")
        self.assertEqual(load_index(self.directory)[0]["outcome"], "loop_completed")

    def test_real_approval_gate_pause_and_resume_is_one_traced_run(self) -> None:
        gate = JSONApprovalGate(
            store=JSONApprovalStore(str(self.directory / "gate" / "queue.json")),
            audit=AuditLogger(str(self.directory / "gate" / "audit.log")),
            authorized_approvers={"Alice"},
            trace_sink=self.logger,
        )
        tool = FakeTool("run_tests", ToolRisk.REQUIRES_APPROVAL)
        runs = []
        original_run = tool.run
        tool.run = lambda arguments, context: runs.append(1) or original_run(
            arguments, context
        )
        request = proposal(Action.RUN_TESTS, {"query": "unit"})
        loop = self.loop(
            ScriptedPlanner(
                request,
                request,
                proposal(Action.PROPOSE_TEST, {"title": "Missing key raises"}),
            ),
            tool=tool,
            gate=gate,
        )

        paused = loop.run(self.task())
        self.assertIs(paused.status, LoopStatus.AWAITING_APPROVAL)
        self.assertEqual(runs, [])

        pending = gate.store.list_pending()
        self.assertEqual(len(pending), 1)
        gate.decide(pending[0].id, approve=True, decided_by="Alice")
        finished = loop.resume(paused)

        self.assertIs(finished.status, LoopStatus.COMPLETED)
        self.assertEqual(runs, [1])
        files = self.run_files()
        self.assertEqual(len(files), 1)
        lines = load_run(files[0])
        actions = [line["action"] for line in lines]
        executed = next(
            index
            for index, line in enumerate(lines)
            if line["action"] == "tool_dispatched"
            and line["tool_invocation"]["output"]["kind"] == "tool_executed"
        )
        self.assertLess(actions.index("loop_paused"), actions.index("approval_granted"))
        self.assertLess(actions.index("approval_granted"), executed)
        granted = lines[actions.index("approval_granted")]
        self.assertEqual(granted["actor"], "human")
        self.assertIn("approver=Alice", granted["detail"])
        self.assertEqual(actions[-1], "loop_completed")

    def test_a_logger_that_cannot_write_fails_the_loop_closed(self) -> None:
        tool_runs = []

        class WatchedTool(FakeTool):
            def run(self, arguments, context):
                tool_runs.append(arguments)
                return super().run(arguments, context)

        with mock.patch.object(
            run_logger_module, "_append_line", side_effect=OSError("disk full")
        ):
            result = self.loop(
                ScriptedPlanner(proposal(Action.SEARCH_REPO, {"query": "q"})),
                tool=WatchedTool(),
            ).run(self.task())

        self.assertIs(result.status, LoopStatus.FAILED)
        self.assertIs(result.failure, LoopFailure.TRACE_FAILED)
        self.assertEqual(tool_runs, [])


if __name__ == "__main__":
    unittest.main()
