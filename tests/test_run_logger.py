"""Unit tests for Member 5's Week 5 run logger.

These feed ``TraceEntry`` objects straight into ``RunLogger`` so they run
without Member 2's agent loop. The end-to-end check with the real loop is
tests/integration/test_run_logger_agent_loop.py.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from models.types import Actor, ToolInvocation, TraceEntry
from observability import RunLogger, format_run, load_index, load_run
from observability import run_logger as run_logger_module

START = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def entry(
    action: str,
    *,
    session_id: str = "session-1",
    seconds: int = 0,
    actor: Actor = Actor.DETERMINISTIC,
    detail: str = "",
    invocation: ToolInvocation | None = None,
) -> TraceEntry:
    return TraceEntry(
        session_id=session_id,
        actor=actor,
        action=action,
        detail=detail or f"event={action}",
        timestamp=START + timedelta(seconds=seconds),
        tool_invocation=invocation,
    )


def tool_call(seconds: int = 2) -> ToolInvocation:
    return ToolInvocation(
        tool_name="read_file",
        input={"argument_keys": ["path"]},
        output={
            "kind": "tool_executed",
            "code": None,
            "output_keys": ["content", "status"],
            "output_bytes": 120,
        },
        called_at=START + timedelta(seconds=seconds),
    )


def completed_run(logger: RunLogger, session_id: str = "session-1") -> None:
    logger.record(entry("loop_started", session_id=session_id))
    logger.record(entry("context_sensed", session_id=session_id, seconds=1))
    logger.record(
        entry("action_planned", session_id=session_id, seconds=1, actor=Actor.AI)
    )
    logger.record(
        entry(
            "tool_dispatched",
            session_id=session_id,
            seconds=2,
            invocation=tool_call(),
        )
    )
    logger.record(entry("loop_completed", session_id=session_id, seconds=3))


class RunLoggerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="run_logger_test_"))
        self.logger = RunLogger(self.directory)

    def tearDown(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def run_files(self) -> list[Path]:
        return sorted(
            path for path in self.directory.glob("*.jsonl") if path.name != "index.jsonl"
        )


class RunFileTests(RunLoggerTestCase):
    def test_every_entry_of_a_run_is_saved_in_order_in_one_file(self) -> None:
        completed_run(self.logger)

        files = self.run_files()
        self.assertEqual(len(files), 1)
        lines = load_run(files[0])
        self.assertEqual(
            [line["action"] for line in lines],
            [
                "loop_started",
                "context_sensed",
                "action_planned",
                "tool_dispatched",
                "loop_completed",
            ],
        )
        self.assertEqual([line["seq"] for line in lines], [1, 2, 3, 4, 5])
        self.assertEqual({line["run_id"] for line in lines}, {lines[0]["run_id"]})
        self.assertEqual(lines[0]["schema"], "qa-agent.run-log/v1")
        self.assertEqual(lines[0]["timestamp"], START.isoformat())
        self.assertEqual(lines[2]["actor"], "ai")

    def test_tool_invocation_metadata_is_serialized(self) -> None:
        completed_run(self.logger)

        dispatched = load_run(self.run_files()[0])[3]
        self.assertEqual(
            dispatched["tool_invocation"],
            {
                "tool_name": "read_file",
                "input": {"argument_keys": ["path"]},
                "output": {
                    "kind": "tool_executed",
                    "code": None,
                    "output_keys": ["content", "status"],
                    "output_bytes": 120,
                },
                "called_at": (START + timedelta(seconds=2)).isoformat(),
            },
        )

    def test_each_new_start_opens_a_new_file_even_for_a_reused_session(self) -> None:
        completed_run(self.logger)
        completed_run(self.logger)
        completed_run(self.logger, session_id="session-2")

        files = self.run_files()
        self.assertEqual(len(files), 3)
        run_ids = {load_run(path)[0]["run_id"] for path in files}
        self.assertEqual(len(run_ids), 3)

    def test_interleaved_sessions_are_kept_in_separate_files(self) -> None:
        self.logger.record(entry("loop_started", session_id="a"))
        self.logger.record(entry("loop_started", session_id="b"))
        self.logger.record(entry("loop_completed", session_id="a", seconds=1))
        self.logger.record(entry("loop_failed", session_id="b", seconds=1))

        by_session = {
            load_run(path)[0]["session_id"]: [line["action"] for line in load_run(path)]
            for path in self.run_files()
        }
        self.assertEqual(
            by_session,
            {"a": ["loop_started", "loop_completed"], "b": ["loop_started", "loop_failed"]},
        )

    def test_entry_without_an_opening_event_is_still_saved(self) -> None:
        self.logger.record(entry("context_sensed"))

        files = self.run_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(load_run(files[0])[0]["action"], "context_sensed")

    def test_session_id_cannot_escape_the_evidence_directory(self) -> None:
        self.logger.record(entry("loop_started", session_id="../../etc/passwd"))

        files = self.run_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent, self.directory)
        self.assertNotIn("/", files[0].name)
        self.assertEqual(load_run(files[0])[0]["session_id"], "../../etc/passwd")


class PauseAndResumeTests(RunLoggerTestCase):
    def test_resumed_run_continues_the_paused_file(self) -> None:
        self.logger.record(entry("loop_started"))
        self.logger.record(entry("loop_paused", seconds=1))
        self.logger.record(entry("loop_resumed", seconds=5))
        self.logger.record(entry("loop_completed", seconds=6))

        files = self.run_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(
            [line["action"] for line in load_run(files[0])],
            ["loop_started", "loop_paused", "loop_resumed", "loop_completed"],
        )

    def test_resume_seen_by_a_new_logger_starts_a_new_file(self) -> None:
        self.logger.record(entry("loop_started"))
        self.logger.record(entry("loop_paused", seconds=1))

        RunLogger(self.directory).record(entry("loop_resumed", seconds=5))

        self.assertEqual(len(self.run_files()), 2)


class IndexTests(RunLoggerTestCase):
    def test_finished_run_appends_one_summary_row(self) -> None:
        completed_run(self.logger)

        rows = load_run(self.directory / "index.jsonl")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["file"], self.run_files()[0].name)
        self.assertEqual(row["session_id"], "session-1")
        self.assertEqual(row["outcome"], "loop_completed")
        self.assertEqual(row["started_at"], START.isoformat())
        self.assertEqual(row["ended_at"], (START + timedelta(seconds=3)).isoformat())
        self.assertEqual(row["entries"], 5)
        self.assertEqual(row["tool_calls"], 1)
        self.assertEqual(row["ai_decisions"], 1)
        self.assertEqual(row["redactions"], 0)

    def test_every_stop_reason_is_indexed(self) -> None:
        for number, outcome in enumerate(
            ("loop_completed", "loop_halted", "loop_failed", "loop_paused")
        ):
            session = f"session-{number}"
            self.logger.record(entry("loop_started", session_id=session))
            self.logger.record(entry(outcome, session_id=session, seconds=1))

        self.assertEqual(
            [row["outcome"] for row in load_index(self.directory)],
            ["loop_completed", "loop_halted", "loop_failed", "loop_paused"],
        )

    def test_load_index_reports_how_a_resumed_run_finally_ended(self) -> None:
        self.logger.record(entry("loop_started"))
        self.logger.record(entry("loop_paused", seconds=1))
        self.logger.record(entry("loop_resumed", seconds=5))
        self.logger.record(entry("loop_halted", seconds=6))

        self.assertEqual(len(load_run(self.directory / "index.jsonl")), 2)
        latest = load_index(self.directory)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["outcome"], "loop_halted")
        self.assertEqual(latest[0]["entries"], 4)

    def test_load_index_of_an_empty_directory_is_empty(self) -> None:
        self.assertEqual(load_index(self.directory), [])


class RedactionTests(RunLoggerTestCase):
    def test_credential_like_strings_never_reach_disk(self) -> None:
        # Built at runtime so this test file itself passes check_sensitive.py.
        google_key = "AIza" + "x" * 35
        bearer = "Bearer " + "a1b2c3d4" * 3
        invocation = ToolInvocation(
            tool_name="search_repo",
            input={"argument_keys": ["query"], "echo": google_key},
            output={"kind": "tool_error", "note": bearer},
            called_at=START,
        )
        self.logger.record(entry("loop_started", detail=f"key={google_key}"))
        self.logger.record(entry("tool_dispatched", invocation=invocation))
        self.logger.record(entry("loop_failed", seconds=1))

        raw = self.run_files()[0].read_text(encoding="utf-8")
        raw_index = (self.directory / "index.jsonl").read_text(encoding="utf-8")
        for text in (raw, raw_index):
            self.assertNotIn(google_key, text)
            self.assertNotIn(bearer, text)
        lines = load_run(self.run_files()[0])
        self.assertTrue(lines[0]["redacted"])
        self.assertIn("[REDACTED]", lines[0]["detail"])
        self.assertTrue(lines[1]["redacted"])
        self.assertNotIn("redacted", lines[2])
        self.assertEqual(load_index(self.directory)[0]["redactions"], 3)


class FailClosedTests(RunLoggerTestCase):
    def test_write_failure_is_raised_not_swallowed(self) -> None:
        with mock.patch.object(
            run_logger_module, "_append_line", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                self.logger.record(entry("loop_started"))

    def test_only_trace_entries_are_accepted(self) -> None:
        with self.assertRaises(TypeError):
            self.logger.record({"action": "loop_started"})  # type: ignore[arg-type]
        self.assertEqual(self.run_files(), [])


class ConfigurationTests(unittest.TestCase):
    def test_directory_defaults_to_the_evidence_traces_folder(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QA_AGENT_TRACE_DIR", None)
            with mock.patch.object(Path, "mkdir"):
                logger = RunLogger()
        self.assertEqual(
            logger.directory.parts[-3:], ("evidence", "traces", "runs")
        )

    def test_environment_variable_overrides_the_directory(self) -> None:
        directory = Path(tempfile.mkdtemp(prefix="run_logger_env_"))
        self.addCleanup(shutil.rmtree, directory, True)
        target = directory / "nested" / "runs"
        with mock.patch.dict(os.environ, {"QA_AGENT_TRACE_DIR": str(target)}):
            logger = RunLogger()
        self.assertEqual(logger.directory, target)
        self.assertTrue(target.is_dir())


class FormatRunTests(RunLoggerTestCase):
    def test_timeline_lists_each_step_and_tool_call(self) -> None:
        completed_run(self.logger)

        text = format_run(load_run(self.run_files()[0]))
        lines = text.splitlines()
        self.assertEqual(len(lines), 6)
        self.assertIn("loop_started", lines[0])
        self.assertIn("tool=read_file", lines[4])
        self.assertIn("kind=tool_executed", lines[4])
        self.assertIn("loop_completed", lines[5])
        json.dumps(text)  # plain text, safe to paste into a report


if __name__ == "__main__":
    unittest.main()
