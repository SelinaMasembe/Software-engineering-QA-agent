"""Week 8 (Member 5): regression tests for the infrastructure fixes from the
final QA review (run logger, run-log viewer, approval data paths)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from models.types import Actor, TraceEntry
from observability import RunLogger, load_index, load_run, resolve_run_log_dir
from observability import run_logger as run_logger_module
from orchestrator import approval_gate

REPO = Path(__file__).resolve().parents[1]
EAT = timezone(timedelta(hours=3))  # Kampala


def entry(action: str, when: datetime, session: str = "s-1") -> TraceEntry:
    return TraceEntry(session_id=session, actor=Actor.DETERMINISTIC, action=action,
                      detail=f"event={action}", timestamp=when)


def load_show_run_log():
    spec = importlib.util.spec_from_file_location("show_run_log", REPO / "scripts" / "show_run_log.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunLoggerFixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="w8_runlog_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_file_name_timestamp_is_converted_to_utc(self) -> None:
        RunLogger(self.directory).record(entry("loop_started", datetime(2026, 10, 23, 13, 0, tzinfo=EAT)))
        names = [p.name for p in self.directory.glob("*.jsonl")]
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("20261023T100000"), names[0])  # 13:00 EAT = 10:00 UTC

    def test_failed_write_does_not_advance_the_counters(self) -> None:
        logger = RunLogger(self.directory)
        when = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
        logger.record(entry("loop_started", when))
        with mock.patch.object(run_logger_module, "_append_line", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                logger.record(entry("context_sensed", when))
        logger.record(entry("loop_completed", when))
        run_file = next(p for p in self.directory.glob("*.jsonl") if p.name != "index.jsonl")
        self.assertEqual([line["seq"] for line in load_run(run_file)], [1, 2])
        self.assertEqual(load_index(self.directory)[0]["entries"], 2)

    def test_load_index_default_follows_the_trace_dir_variable(self) -> None:
        logger = RunLogger(self.directory)
        logger.record(entry("loop_started", datetime(2026, 10, 23, tzinfo=timezone.utc)))
        logger.record(entry("loop_completed", datetime(2026, 10, 23, tzinfo=timezone.utc)))
        with mock.patch.dict(os.environ, {"QA_AGENT_TRACE_DIR": str(self.directory)}):
            self.assertEqual(resolve_run_log_dir(), self.directory)
            self.assertEqual([row["outcome"] for row in load_index()], ["loop_completed"])


class ShowRunLogFixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="w8_show_"))
        self.viewer = load_show_run_log()

    def tearDown(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def run_viewer(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.viewer.main(list(args))
        return code, out.getvalue()

    def test_listing_a_missing_folder_does_not_create_it(self) -> None:
        missing = self.directory / "not-there"
        code, output = self.run_viewer("--dir", str(missing))
        self.assertEqual(code, 0)
        self.assertFalse(missing.exists())
        self.assertIn("No finished runs", output)

    def test_a_listed_file_name_can_be_passed_back(self) -> None:
        logger = RunLogger(self.directory)
        when = datetime(2026, 10, 23, tzinfo=timezone.utc)
        logger.record(entry("loop_started", when))
        logger.record(entry("loop_completed", when))
        name = load_index(self.directory)[0]["file"]
        code, output = self.run_viewer("--dir", str(self.directory), name)
        self.assertEqual(code, 0)
        self.assertIn("loop_completed", output)

    def test_unknown_file_is_a_clean_error(self) -> None:
        code, output = self.run_viewer("--dir", str(self.directory), "nope.jsonl")
        self.assertEqual(code, 1)
        self.assertIn("No run file", output)


class AgentSessionTraceDirTests(unittest.TestCase):
    """run_agent_session.py --trace-dir saves the real session's run log."""

    def test_offline_session_writes_a_replayable_run_log(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "run_agent_session", REPO / "scripts" / "run_agent_session.py")
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        directory = Path(tempfile.mkdtemp(prefix="w8_session_"))
        self.addCleanup(shutil.rmtree, directory, True)
        with contextlib.redirect_stdout(io.StringIO()):
            code = script.main([
                "--goal", "Propose a test that the account locks after five failed login attempts.",
                "--trace-dir", str(directory),
            ])
        self.assertEqual(code, 0)
        rows = load_index(directory)
        self.assertEqual([row["outcome"] for row in rows], ["loop_completed"])
        actions = [line["action"] for line in load_run(directory / rows[0]["file"])]
        self.assertEqual(actions[0], "loop_started")
        self.assertIn("action_planned", actions)

    def test_without_the_option_nothing_is_written(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "run_agent_session_plain", REPO / "scripts" / "run_agent_session.py")
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        self.assertIsNone(script.build_parser().parse_args([]).trace_dir)
        self.assertIsNone(script.MemorySink().also)


class ApprovalDataPathTests(unittest.TestCase):
    def test_default_queue_and_audit_live_in_the_repository_data_folder(self) -> None:
        self.assertEqual(approval_gate.DEFAULT_DATA_DIR, REPO / "data")
        with mock.patch.object(approval_gate.os, "makedirs"), \
             mock.patch.object(approval_gate.JSONApprovalStore, "_write"), \
             mock.patch.object(approval_gate.os.path, "exists", return_value=True), \
             mock.patch.object(approval_gate, "_exclusive_file_lock") as lock:
            lock.return_value.__enter__ = lambda *a: None
            lock.return_value.__exit__ = lambda *a: False
            store = approval_gate.JSONApprovalStore()
            audit = approval_gate.AuditLogger()
        self.assertEqual(Path(store.path), REPO / "data" / "approval_queue.json")
        self.assertEqual(Path(audit.path), REPO / "data" / "audit.log")


if __name__ == "__main__":
    unittest.main()
