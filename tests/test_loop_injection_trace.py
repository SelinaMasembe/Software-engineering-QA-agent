"""Week 8 guardrail fix (Member 4, Quality/Security Lead): a flagged chunk's
injection/credential flags must actually reach the trace, not just be
computed and discarded.

Found during the Week 8 hardening pass: src/rag/injection_flagging.py and
src/rag/credential_scan.py correctly detect injection-shaped and
credential-shaped content per chunk, and src/rag/context_builder.py
correctly attaches the result to AssembledContext.flagged. But
src/agent/loop.py's AgentLoop never read that field -- its CONTEXT_SENSED
trace entry recorded only not_in_corpus and the allowed-source count, and
injection_flagging.flag_trace_entry (the function written to turn flags
into a trace entry) was called only by its own tests, never by the loop.
Risk R1 ("flagged during ingestion for review") was therefore not actually
achieved for a real session: a human reading the trace had no way to learn
that a chunk had been flagged at all.

The fix (src/agent/loop.py): when context.flagged is non-empty, AgentLoop
now records the flag_trace_entry alongside CONTEXT_SENSED, using the same
fail-closed trace-sink path every other trace entry already uses. This file
proves the fix; it does not replace tests/integration/test_agent_loop.py,
which continues to own the loop's general trace-sequence behaviour -- none
of its existing fixtures populate AssembledContext.flagged, which is why
those 26 tests still pass unchanged after this fix.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent import AgentLoop, AgentTask, LoopFailure, LoopStatus  # noqa: E402
from models.types import (  # noqa: E402
    Action,
    Confidence,
    EvidenceRef,
    ProposalSet,
    StopReason,
    TraceEntry,
)
from orchestrator import ExecutionContext  # noqa: E402
from rag import AssembledContext  # noqa: E402
from rag.injection_flagging import CATEGORIES, InjectionFlag, TRACE_ACTION, ChunkFlags  # noqa: E402

SOURCE = "requirements/auth.md"
CONTEXT = ExecutionContext(session_id="session-1", actor_id="dev-1", role="developer")
TASK = AgentTask(goal="Propose tests for the login lockout requirement.", context=CONTEXT)
FIXED_NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _flagged_chunk(rule_id: str = "IO-1") -> ChunkFlags:
    return ChunkFlags(
        chunk_id=f"{SOURCE}#L1-L2",
        source_path=SOURCE,
        doc_type="requirement",
        flags=(InjectionFlag(rule_id, CATEGORIES[0], 0, 10),),
    )


def _context(*, flagged: tuple[ChunkFlags, ...] = ()) -> AssembledContext:
    return AssembledContext(
        text="<evidence source_path=\"requirements/auth.md\">fixture</evidence>",
        chunks_used=1,
        chunks_dropped=0,
        not_in_corpus=False,
        allowed_source_paths=frozenset({SOURCE}),
        flagged=flagged,
    )


class ScriptedSensor:
    def __init__(self, context: AssembledContext) -> None:
        self.context = context

    def sense(self, task, state):
        return self.context


class ScriptedPlanner:
    def plan(self, task, context, state):
        return ProposalSet(
            action=Action.PROPOSE_TEST,
            arguments={"title": "Lock account after five failures"},
            rationale="Grounded in the supplied context.",
            evidence=(EvidenceRef(source_path=SOURCE),),
            confidence=Confidence.HIGH,
        )


class NullDispatcher:
    def dispatch(self, proposal, *, context):
        raise AssertionError("PROPOSE_TEST must never be dispatched.")


class FakeStopEvaluator:
    def evaluate(self, state):
        return None if state.iterations_completed == 0 else StopReason.ITERATION_CAP


class RecordingTraceSink:
    def __init__(self) -> None:
        self.entries: list[TraceEntry] = []

    def record(self, entry: TraceEntry) -> None:
        self.entries.append(entry)

    @property
    def actions(self) -> list[str]:
        return [entry.action for entry in self.entries]


class RaisingTraceSink:
    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on
        self.seen: list[str] = []

    def record(self, entry: TraceEntry) -> None:
        self.seen.append(entry.action)
        if entry.action == self.fail_on:
            raise RuntimeError("trace backend unavailable")


def _make_loop(context: AssembledContext, trace_sink):
    return AgentLoop(
        sensor=ScriptedSensor(context),
        planner=ScriptedPlanner(),
        dispatcher=NullDispatcher(),
        stop_evaluator=FakeStopEvaluator(),
        trace_sink=trace_sink,
        clock=lambda: FIXED_NOW,
    )


class InjectionFlagsReachTheTraceTests(unittest.TestCase):
    def test_a_flagged_chunk_produces_an_injection_flagged_trace_entry(self) -> None:
        trace = RecordingTraceSink()
        loop = _make_loop(_context(flagged=(_flagged_chunk(),)), trace)

        result = loop.run(TASK)

        self.assertIs(result.status, LoopStatus.COMPLETED)
        self.assertIn(TRACE_ACTION, trace.actions)
        entry = next(e for e in trace.entries if e.action == TRACE_ACTION)
        self.assertEqual(entry.session_id, "session-1")
        self.assertIn("IO-1", entry.detail)
        self.assertIn("chunks_flagged=1", entry.detail)
        # Comes right after context_sensed, before the turn is planned.
        self.assertEqual(
            trace.actions[:3], ["loop_started", "context_sensed", TRACE_ACTION]
        )

    def test_an_unflagged_turn_records_no_injection_flagged_entry(self) -> None:
        trace = RecordingTraceSink()
        loop = _make_loop(_context(), trace)

        loop.run(TASK)

        self.assertNotIn(TRACE_ACTION, trace.actions)

    def test_multiple_flagged_chunks_are_combined_into_one_entry(self) -> None:
        trace = RecordingTraceSink()
        two_chunks = (_flagged_chunk("IO-1"), _flagged_chunk("TB-1"))
        loop = _make_loop(_context(flagged=two_chunks), trace)

        loop.run(TASK)

        entry = next(e for e in trace.entries if e.action == TRACE_ACTION)
        self.assertIn("chunks_flagged=2", entry.detail)
        self.assertIn("IO-1", entry.detail)
        self.assertIn("TB-1", entry.detail)

    def test_the_trace_entry_never_carries_the_flagged_chunk_text(self) -> None:
        trace = RecordingTraceSink()
        loop = _make_loop(_context(flagged=(_flagged_chunk(),)), trace)

        loop.run(TASK)

        entry = next(e for e in trace.entries if e.action == TRACE_ACTION)
        self.assertNotIn("fixture", entry.detail)
        self.assertNotIn(SOURCE, entry.detail)

    def test_a_trace_sink_failure_on_the_flag_entry_fails_the_loop_closed(self) -> None:
        trace = RaisingTraceSink(fail_on=TRACE_ACTION)
        loop = _make_loop(_context(flagged=(_flagged_chunk(),)), trace)

        result = loop.run(TASK)

        self.assertIs(result.status, LoopStatus.FAILED)
        self.assertIs(result.failure, LoopFailure.TRACE_FAILED)


if __name__ == "__main__":
    unittest.main()
