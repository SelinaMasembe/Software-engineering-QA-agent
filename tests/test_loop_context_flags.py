"""The loop records context flags itself (LoopEvent.CONTEXT_FLAGGED).

Week 8, Member 3, applied to src/agent/loop.py at the team's request. Any
sensor's flags now reach the trace, not only the real sensor's. The detail is
counts, categories and rule ids only: never chunk text or a source path.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from agent.loop import AgentLoop, AgentTask, LoopEvent, LoopFailure, LoopStatus
from models.types import Action, Confidence, EvidenceRef, ProposalSet
from orchestrator import ExecutionContext, ToolDispatcher, ToolRegistry
from rag import AssembledContext
from rag.credential_scan import CredentialFlag
from rag.injection_flagging import ChunkFlags, InjectionFlag

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
SOURCE = "src/secret_named_module.py"
TASK = AgentTask(
    goal="Propose a test.",
    context=ExecutionContext(session_id="session-f", actor_id="dev-1", role="developer"),
)


def flagged_context(flagged) -> AssembledContext:
    return AssembledContext(
        text=f'<evidence source_path="{SOURCE}" doc_type="code">\nx\n</evidence>',
        chunks_used=1, chunks_dropped=0, not_in_corpus=False,
        allowed_source_paths=frozenset({SOURCE}), flagged=flagged,
    )


TWO_FLAGS = (
    ChunkFlags(f"{SOURCE}#L1-L1", SOURCE, "code", (
        InjectionFlag("AI-1", "action_imperative_aimed_at_agent", 0, 10),
        CredentialFlag("CR-AWS-KEY", 12, 32),
    )),
)


class Sensor:
    def __init__(self, context) -> None:
        self.context = context

    def sense(self, task, state):
        return self.context


class Planner:
    def plan(self, task, context, state):
        return ProposalSet(
            action=Action.PROPOSE_TEST, arguments={"title": "t"}, rationale="r",
            evidence=(EvidenceRef(SOURCE),), confidence=Confidence.HIGH,
        )


class NeverStop:
    def evaluate(self, state):
        return None


class Sink:
    def __init__(self, fail_on: str | None = None) -> None:
        self.entries = []
        self.fail_on = fail_on

    def record(self, entry) -> None:
        if entry.action == self.fail_on:
            raise OSError("disk full")
        self.entries.append(entry)


def run(context, sink=None):
    sink = sink or Sink()
    loop = AgentLoop(
        sensor=Sensor(context), planner=Planner(),
        dispatcher=ToolDispatcher(ToolRegistry([])), stop_evaluator=NeverStop(),
        trace_sink=sink, clock=lambda: NOW,
    )
    return loop.run(TASK), sink


class LoopContextFlagTests(unittest.TestCase):
    def test_flags_are_recorded_right_after_the_context_is_sensed(self) -> None:
        result, sink = run(flagged_context(TWO_FLAGS))

        self.assertIs(result.status, LoopStatus.COMPLETED)
        actions = [e.action for e in sink.entries]
        sensed = actions.index(LoopEvent.CONTEXT_SENSED.value)
        self.assertEqual(actions[sensed + 1], LoopEvent.CONTEXT_FLAGGED.value)
        detail = sink.entries[sensed + 1].detail
        self.assertEqual(
            detail,
            "iteration=1; chunks_flagged=1; flags=2; "
            "categories=action_imperative_aimed_at_agent,credential; rules=AI-1,CR-AWS-KEY",
        )
        self.assertNotIn("secret_named_module", detail)

    def test_no_flags_means_no_new_event(self) -> None:
        _, sink = run(flagged_context(()))
        self.assertNotIn(LoopEvent.CONTEXT_FLAGGED.value, [e.action for e in sink.entries])

    def test_rule_ids_and_categories_are_reduced_to_safe_characters(self) -> None:
        class OddFlag:
            rule_id = "AI-1; rm -rf /"
            category = "note <b>"

        odd = (ChunkFlags("c", SOURCE, "code", ()),)
        object.__setattr__(odd[0], "flags", (OddFlag(),))

        _, sink = run(flagged_context(odd))

        detail = next(e.detail for e in sink.entries if e.action == LoopEvent.CONTEXT_FLAGGED.value)
        self.assertIn("rules=AI-1rm-rf", detail)
        self.assertIn("categories=noteb", detail)
        self.assertNotIn(";", detail.split("rules=")[1])

    def test_a_malformed_flagged_value_fails_the_sense_step(self) -> None:
        result, _ = run(flagged_context("not a tuple"))

        self.assertIs(result.status, LoopStatus.FAILED)
        self.assertIs(result.failure, LoopFailure.SENSE_FAILED)

    def test_a_sink_failure_on_the_flag_entry_fails_closed(self) -> None:
        result, _ = run(flagged_context(TWO_FLAGS), Sink(fail_on=LoopEvent.CONTEXT_FLAGGED.value))

        self.assertIs(result.status, LoopStatus.FAILED)
        self.assertIs(result.failure, LoopFailure.TRACE_FAILED)


if __name__ == "__main__":
    unittest.main()
