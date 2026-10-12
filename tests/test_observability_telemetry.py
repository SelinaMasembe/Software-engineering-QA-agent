"""Unit tests for Member 2's Week 7 step-telemetry recorder.

These cover the recorder, its sinks and the summary on their own. How the
instrumentation wraps the agent loop is tested in
tests/integration/test_observability_agent_loop.py.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

from observability.telemetry import (
    SCHEMA_VERSION,
    InMemoryStepSink,
    JsonlStepSink,
    ObservabilityRecorder,
    StepKind,
    load_steps,
)

FIXED_NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


class SteppingTimer:
    """Monotonic fake: every read advances by ``step`` seconds."""

    def __init__(self, step: float = 0.010) -> None:
        self.now = 100.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


class SteppingClock:
    def __init__(self) -> None:
        self.now = FIXED_NOW

    def __call__(self) -> datetime:
        value = self.now
        self.now += timedelta(milliseconds=10)
        return value


class FailingSink:
    def __init__(self) -> None:
        self.calls = 0

    def write(self, record) -> None:
        self.calls += 1
        raise OSError("disk full")


def recorder(*sinks, timer=None) -> ObservabilityRecorder:
    return ObservabilityRecorder(
        "session-7",
        sinks=sinks,
        clock=SteppingClock(),
        timer=timer or SteppingTimer(),
    )


class RecorderTests(unittest.TestCase):
    def test_step_records_kind_duration_and_attributes(self) -> None:
        rec = recorder()
        with rec.step(StepKind.TOOL_CALL) as scope:
            scope.set(tool="search_repo", argument_keys=["query"])

        (record,) = rec.records
        self.assertEqual(record.session_id, "session-7")
        self.assertEqual(record.seq, 1)
        self.assertIs(record.kind, StepKind.TOOL_CALL)
        self.assertEqual(record.started_at, FIXED_NOW)
        self.assertEqual(record.duration_ms, 10.0)
        self.assertTrue(record.ok)
        self.assertIsNone(record.error_type)
        self.assertEqual(record.attributes["tool"], "search_repo")
        self.assertEqual(record.attributes["argument_keys"], ("query",))

    def test_failed_step_keeps_type_name_and_reraises_original(self) -> None:
        rec = recorder()
        error = RuntimeError("token=test-secret-placeholder")
        with self.assertRaises(RuntimeError) as raised:
            with rec.step(StepKind.SENSE):
                raise error

        self.assertIs(raised.exception, error)
        (record,) = rec.records
        self.assertFalse(record.ok)
        self.assertEqual(record.error_type, "RuntimeError")
        self.assertNotIn("test-secret-placeholder", repr(record.to_dict()))

    def test_sequence_numbers_follow_completion_order(self) -> None:
        rec = recorder()
        for kind in (StepKind.SENSE, StepKind.PLAN, StepKind.TOOL_CALL):
            with rec.step(kind):
                pass
        self.assertEqual([r.seq for r in rec.records], [1, 2, 3])
        self.assertEqual(
            [r.kind for r in rec.records],
            [StepKind.SENSE, StepKind.PLAN, StepKind.TOOL_CALL],
        )

    def test_records_and_attributes_are_read_only_copies(self) -> None:
        sources = ["a.py"]
        rec = recorder()
        with rec.step(StepKind.RETRIEVAL) as scope:
            scope.set(source_paths=sources, usage={"total": 3})
        sources.append("b.py")

        record = rec.records[0]
        self.assertEqual(record.attributes["source_paths"], ("a.py",))
        with self.assertRaises(TypeError):
            record.attributes["source_paths"] = ()  # type: ignore[index]
        with self.assertRaises(TypeError):
            record.attributes["usage"]["total"] = 4  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            record.ok = False  # type: ignore[misc]

    def test_non_json_attribute_is_refused(self) -> None:
        rec = recorder()
        with rec.step(StepKind.PLAN) as scope:
            with self.assertRaises(TypeError):
                scope.set(handle=object())
            with self.assertRaises(TypeError):
                scope.set(latency=float("nan"))
        self.assertEqual(dict(rec.records[0].attributes), {})

    def test_capture_marks_unreadable_results_instead_of_raising(self) -> None:
        rec = recorder()
        with rec.step(StepKind.SENSE) as scope:
            scope.capture(lambda: {"chunks_used": None.real})  # type: ignore[attr-defined]
        attributes = rec.records[0].attributes
        self.assertTrue(rec.records[0].ok)
        self.assertEqual(dict(attributes), {"attributes_unavailable": True})

    def test_requires_session_id_and_sinks_with_write(self) -> None:
        with self.assertRaises(ValueError):
            ObservabilityRecorder("  ")
        with self.assertRaises(ValueError):
            ObservabilityRecorder("s", sinks=[object()])


class SinkTests(unittest.TestCase):
    def test_in_memory_sink_receives_every_record(self) -> None:
        sink = InMemoryStepSink()
        rec = recorder(sink)
        with rec.step(StepKind.SENSE):
            pass
        with rec.step(StepKind.PLAN):
            pass
        self.assertEqual(list(rec.records), sink.records)

    def test_failing_sink_is_counted_and_never_raised(self) -> None:
        failing = FailingSink()
        memory = InMemoryStepSink()
        rec = recorder(failing, memory)
        with rec.step(StepKind.TOOL_CALL):
            pass
        with rec.step(StepKind.TOOL_CALL):
            pass

        self.assertEqual(failing.calls, 2)
        self.assertEqual(rec.dropped_writes, 2)
        self.assertEqual(len(memory.records), 2)
        self.assertEqual(len(rec.records), 2)
        self.assertEqual(rec.summary()["dropped_writes"], 2)

    def test_sink_may_read_the_recorder_while_writing(self) -> None:
        seen: list[int] = []

        class SummarizingSink:
            def write(self, record) -> None:
                seen.append(rec.summary()["steps"])

        rec = recorder(SummarizingSink())
        with rec.step(StepKind.SENSE):
            pass
        with rec.step(StepKind.PLAN):
            pass
        self.assertEqual(seen, [1, 2])

    def test_jsonl_sink_writes_one_line_per_record_per_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sink = JsonlStepSink(Path(tmp) / "telemetry")
            rec = recorder(sink)
            with rec.step(StepKind.MODEL_CALL) as scope:
                scope.set(model="demo-model", total_tokens=42)
            with rec.step(StepKind.PLAN) as scope:
                scope.set(action="propose_test")

            path = sink.path_for("session-7")
            self.assertIsNotNone(path)
            self.assertEqual(path.suffix, ".jsonl")
            self.assertIn("session-7", path.name)
            lines = load_steps(path)
            self.assertEqual(lines, [r.to_dict() for r in rec.records])
            self.assertEqual(lines[0]["schema"], SCHEMA_VERSION)
            self.assertEqual(lines[0]["attributes"]["total_tokens"], 42)
            for raw in path.read_text(encoding="utf-8").splitlines():
                json.loads(raw)

    def test_jsonl_filename_drops_unsafe_session_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sink = JsonlStepSink(tmp)
            rec = ObservabilityRecorder(
                "../../etc/passwd ü", sinks=[sink], clock=SteppingClock(),
                timer=SteppingTimer(),
            )
            with rec.step(StepKind.SENSE):
                pass
            path = sink.path_for("../../etc/passwd ü")
            self.assertEqual(path.parent, Path(tmp))
            self.assertNotIn("/", path.name)
            self.assertTrue(path.name.isascii())


class SummaryTests(unittest.TestCase):
    def test_summary_aggregates_timing_model_retrieval_and_tools(self) -> None:
        rec = recorder()
        with rec.step(StepKind.RETRIEVAL) as scope:
            scope.set(
                not_in_corpus=False,
                chunks_returned=2,
                source_paths=["b.md", "a.py"],
            )
        with rec.step(StepKind.MODEL_CALL) as scope:
            scope.set(
                model="demo-model",
                prompt_version="v1.2",
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                provider_latency_ms=250,
            )
        with rec.step(StepKind.PLAN) as scope:
            scope.set(action="search_repo")
        with rec.step(StepKind.TOOL_CALL) as scope:
            scope.set(tool="search_repo", status="executed")
        with self.assertRaises(ValueError):
            with rec.step(StepKind.TOOL_CALL) as scope:
                scope.set(tool="run_tests")
                raise ValueError("boom")
        with rec.step(StepKind.LOOP_EVENT) as scope:
            scope.set(event="loop_completed")

        summary = rec.summary()
        json.dumps(summary)  # JSON-ready
        self.assertEqual(summary["steps"], 6)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["elapsed_ms"], 110.0)
        self.assertEqual(summary["by_kind"]["tool_call"]["count"], 2)
        self.assertEqual(summary["by_kind"]["tool_call"]["errors"], 1)
        self.assertEqual(summary["by_kind"]["tool_call"]["mean_ms"], 10.0)
        self.assertEqual(summary["model"]["models"], ["demo-model"])
        self.assertEqual(summary["model"]["prompt_versions"], ["v1.2"])
        self.assertEqual(summary["model"]["total_tokens"], 120)
        self.assertEqual(summary["model"]["planned_actions"], ["search_repo"])
        self.assertEqual(summary["retrieval"]["chunks_returned"], 2)
        self.assertEqual(summary["retrieval"]["sources"], ["a.py", "b.md"])
        self.assertEqual(
            summary["tools"]["by_tool"], {"run_tests": 1, "search_repo": 1}
        )
        self.assertEqual(
            summary["tools"]["by_status"], {"executed": 1, "unknown": 1}
        )
        self.assertEqual(summary["outcome"], "loop_completed")

    def test_empty_summary_has_no_totals(self) -> None:
        summary = recorder().summary()
        self.assertEqual(summary["steps"], 0)
        self.assertEqual(summary["elapsed_ms"], 0.0)
        self.assertIsNone(summary["model"]["total_tokens"])
        self.assertIsNone(summary["outcome"])


if __name__ == "__main__":
    unittest.main()
