"""Member 5's Week 6 memory retention tests.

A real MemoryStore in a temporary directory and an injected clock, matching
tests/test_memory_api.py. Records are written through Member 3's
ProposalMemory, so they are exactly what the agent would store.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from memory.api import ProposalMemory, namespace_for_module
from memory.retention import (
    MEMORY_EXPIRES_AFTER,
    RetentionAudit,
    clear_module,
    main as retention_main,
    purge_expired,
    run_scheduled,
    validate_handle,
)
from memory.store import MemoryStore
from models.types import Confidence, EvidenceRef, ProposalMemoryStatus, TestProposal

SRC = Path(__file__).resolve().parents[1] / "src"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
START = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
LOGIN = "src/auth/login.py"
BILLING = "src/billing/discounts.py"


def proposal(title: str) -> TestProposal:
    return TestProposal(
        title=title,
        target=None,
        rationale="Grounded in the requirement.",
        evidence=(EvidenceRef(source_path="requirements/authentication.md"),),
        confidence=Confidence.HIGH,
        requirement_id="REQ-AUTH-01",
    )


class RetentionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.db_path = self.root / "memory.sqlite3"
        self.store = MemoryStore(self.db_path)
        self.now = START
        self.audit = RetentionAudit(self.root / "memory_audit.jsonl")

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def memory(self, expires_after: timedelta | None) -> ProposalMemory:
        return ProposalMemory(self.store, expires_after=expires_after, clock=lambda: self.now)

    def remembered(self, module: str) -> int:
        return len(self.store.list(namespace_for_module(module), limit=1000))

    def audit_events(self) -> list[dict]:
        path = self.audit.path
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class PolicyTests(RetentionTestCase):
    def test_team_decision_is_keep_until_a_human_clears(self) -> None:
        self.assertIsNone(MEMORY_EXPIRES_AFTER)

    def test_option_a_records_are_never_deleted_by_the_job(self) -> None:
        memory = self.memory(MEMORY_EXPIRES_AFTER)
        memory.record_proposal(LOGIN, proposal("Lock account after five failures"))
        memory_key = memory.list_for_module(LOGIN)[0].proposal_key
        memory.record_rejection(LOGIN, memory_key, by="qa-lead")

        report = purge_expired(self.store, now=START + timedelta(days=3650), audit=self.audit)

        self.assertEqual(report.deleted, ())
        self.assertEqual(self.remembered(LOGIN), 1)


class PurgeExpiredTests(RetentionTestCase):
    def test_only_records_past_their_expiry_are_deleted(self) -> None:
        self.memory(timedelta(days=30)).record_proposal(LOGIN, proposal("Old proposal"))
        self.now = START + timedelta(days=20)
        self.memory(timedelta(days=30)).record_proposal(BILLING, proposal("Newer proposal"))

        report = purge_expired(self.store, now=START + timedelta(days=31), audit=self.audit)

        self.assertEqual(len(report.deleted), 1)
        self.assertEqual(report.deleted[0].namespace, namespace_for_module(LOGIN))
        self.assertEqual(self.remembered(LOGIN), 0)
        self.assertEqual(self.remembered(BILLING), 1)

    def test_records_without_an_expiry_are_never_deleted(self) -> None:
        self.memory(timedelta(days=1)).record_proposal(LOGIN, proposal("Expires"))
        self.memory(None).record_proposal(BILLING, proposal("Kept until cleared"))

        purge_expired(self.store, now=START + timedelta(days=3650), audit=self.audit)

        self.assertEqual(self.remembered(LOGIN), 0)
        self.assertEqual(self.remembered(BILLING), 1)

    def test_an_expiry_exactly_now_counts_as_passed(self) -> None:
        self.memory(timedelta(days=30)).record_proposal(LOGIN, proposal("Boundary"))

        report = purge_expired(self.store, now=START + timedelta(days=30))

        self.assertEqual(len(report.deleted), 1)

    def test_dry_run_lists_but_deletes_nothing(self) -> None:
        self.memory(timedelta(days=1)).record_proposal(LOGIN, proposal("Expired"))

        report = purge_expired(self.store, now=START + timedelta(days=2), dry_run=True)

        self.assertTrue(report.dry_run)
        self.assertEqual(len(report.deleted), 1)
        self.assertEqual(self.remembered(LOGIN), 1)

    def test_a_record_that_changed_after_listing_is_skipped_not_deleted(self) -> None:
        memory = self.memory(timedelta(days=30))
        record = memory.record_proposal(LOGIN, proposal("Will be run"))
        self.now = START + timedelta(days=31)
        stale = self.store.list_expired(before=self.now, limit=10)
        memory.record_run(LOGIN, record.proposal_key)  # newer write, fresh expiry

        class StaleListingStore:
            def __init__(self, store, listing):
                self._store, self._listing = store, listing

            def list_expired(self, *, before, limit):
                listing, self._listing = self._listing, ()
                return listing

            def delete(self, *args, **kwargs):
                return self._store.delete(*args, **kwargs)

        report = purge_expired(StaleListingStore(self.store, stale), now=self.now)

        self.assertEqual(report.deleted, ())
        self.assertEqual(report.skipped_changed, 1)
        self.assertEqual(
            memory.find(LOGIN, record.proposal_key).status, ProposalMemoryStatus.RUN
        )

    def test_large_backlogs_are_deleted_in_batches(self) -> None:
        memory = self.memory(timedelta(days=1))
        for number in range(7):
            memory.record_proposal(LOGIN, proposal(f"Proposal {number}"))

        report = purge_expired(self.store, now=START + timedelta(days=2), batch_size=2)

        self.assertEqual(len(report.deleted), 7)
        self.assertEqual(self.remembered(LOGIN), 0)

    def test_one_run_stops_at_its_deletion_limit(self) -> None:
        memory = self.memory(timedelta(days=1))
        for number in range(5):
            memory.record_proposal(LOGIN, proposal(f"Proposal {number}"))

        report = purge_expired(
            self.store, now=START + timedelta(days=2), batch_size=2, max_deletions=3
        )

        self.assertTrue(report.reached_limit)
        self.assertEqual(len(report.deleted), 3)
        self.assertEqual(self.remembered(LOGIN), 2)

    def test_every_deletion_and_run_is_audited_without_stored_text(self) -> None:
        self.memory(timedelta(days=1)).record_proposal(
            LOGIN, proposal("Secret-looking title text")
        )

        purge_expired(self.store, now=START + timedelta(days=2), audit=self.audit)

        events = self.audit_events()
        self.assertEqual(
            [event["event"] for event in events], ["memory_record_deleted", "retention_run"]
        )
        self.assertEqual(events[0]["reason"], "expired")
        self.assertEqual(events[1]["deleted"], 1)
        self.assertNotIn("Secret-looking", self.audit.path.read_text(encoding="utf-8"))

    def test_the_cutoff_must_be_timezone_aware(self) -> None:
        with self.assertRaises(ValueError):
            purge_expired(self.store, now=datetime(2026, 10, 9))


class ScheduleTests(RetentionTestCase):
    def test_each_scheduled_run_opens_and_closes_its_own_store(self) -> None:
        self.memory(timedelta(days=1)).record_proposal(LOGIN, proposal("Expired"))
        opened: list[MemoryStore] = []
        reports = []

        def open_store() -> MemoryStore:
            opened.append(MemoryStore(self.db_path))
            return opened[-1]

        runs = run_scheduled(
            open_store,
            interval_seconds=0.01,
            clock=lambda: START + timedelta(days=2),
            max_runs=3,
            on_report=reports.append,
        )

        self.assertEqual(runs, 3)
        self.assertEqual(len(opened), 3)
        self.assertEqual([len(report.deleted) for report in reports], [1, 0, 0])
        with self.assertRaises(Exception):
            opened[0].list(namespace_for_module(LOGIN))  # closed after its run

    def test_a_failed_run_is_audited_and_the_schedule_continues(self) -> None:
        attempts = []

        def flaky_store() -> MemoryStore:
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("database locked")
            return MemoryStore(self.db_path)

        runs = run_scheduled(
            flaky_store, interval_seconds=0.01, audit=self.audit, max_runs=2
        )

        self.assertEqual(runs, 2)
        events = [event["event"] for event in self.audit_events()]
        self.assertEqual(events, ["retention_run_failed", "retention_run"])

    def test_setting_the_stop_event_ends_the_schedule(self) -> None:
        stop = threading.Event()
        stop.set()

        runs = run_scheduled(lambda: MemoryStore(self.db_path), interval_seconds=60, stop_event=stop)

        self.assertEqual(runs, 0)

    def test_the_interval_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            run_scheduled(lambda: self.store, interval_seconds=0, max_runs=1)


class ClearModuleTests(RetentionTestCase):
    def setUp(self) -> None:
        super().setUp()
        memory = self.memory(None)
        memory.record_proposal(LOGIN, proposal("Lock account after five failures"))
        memory.record_proposal(LOGIN, proposal("Reset counter after success"))
        memory.record_proposal(BILLING, proposal("Discount applied once"))

    def clear(self, **overrides):
        options = dict(
            by="qa-lead",
            reason="module rewritten",
            now=self.now,
            audit=self.audit,
            authorized={"qa-lead"},
        )
        options.update(overrides)
        return clear_module(self.store, LOGIN, **options)

    def test_without_confirm_it_only_previews(self) -> None:
        report = self.clear()

        self.assertTrue(report.dry_run)
        self.assertEqual(len(report.deleted), 2)
        self.assertEqual(self.remembered(LOGIN), 2)
        self.assertEqual(self.audit_events()[-1]["event"], "memory_clear_previewed")

    def test_confirm_deletes_only_that_module(self) -> None:
        report = self.clear(confirm=True)

        self.assertFalse(report.dry_run)
        self.assertEqual(len(report.deleted), 2)
        self.assertEqual(self.remembered(LOGIN), 0)
        self.assertEqual(self.remembered(BILLING), 1)
        final = self.audit_events()[-1]
        self.assertEqual(final["event"], "memory_module_cleared")
        self.assertEqual(final["by"], "qa-lead")
        self.assertEqual(final["reason"], "module rewritten")

    def test_module_spelling_is_normalised(self) -> None:
        self.clear(confirm=True)
        self.assertEqual(self.remembered("./src\\auth/login.py"), 0)

    def test_a_personal_email_or_blank_handle_is_refused(self) -> None:
        for bad in ("alice@example.com", "Alice Smith", "", "   "):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.clear(by=bad, confirm=True)
        self.assertEqual(self.remembered(LOGIN), 2)

    def test_an_unauthorized_handle_is_refused_and_audited(self) -> None:
        with self.assertRaises(PermissionError):
            self.clear(by="intern", confirm=True)

        self.assertEqual(self.remembered(LOGIN), 2)
        self.assertEqual(self.audit_events()[-1]["event"], "memory_clear_refused")

    def test_a_reason_is_required(self) -> None:
        with self.assertRaises(ValueError):
            self.clear(reason="  ", confirm=True)
        self.assertEqual(self.remembered(LOGIN), 2)

    def test_handles_are_role_style(self) -> None:
        self.assertEqual(validate_handle(" qa-lead "), "qa-lead")
        self.assertEqual(validate_handle("team_j.reviewers"), "team_j.reviewers")


class HumanOnlyBoundaryTests(unittest.TestCase):
    """The agent and its tools must never reach retention (deletion) code."""

    def test_agent_and_tool_code_do_not_import_retention(self) -> None:
        offenders = []
        for package in ("agent", "tools"):
            for path in sorted((SRC / package).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if _reaches_retention(node):
                        offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_the_boundary_check_would_catch_an_import(self) -> None:
        for source in (
            "import memory.retention",
            "from memory.retention import clear_module",
            "from memory import retention",
            "from memory.retention import purge_expired",
            "x.clear_module(store, 'm', by='a')",
        ):
            with self.subTest(source=source):
                self.assertTrue(any(_reaches_retention(n) for n in ast.walk(ast.parse(source))))
        harmless = ast.parse("from memory.store import MemoryStore\nimport json")
        self.assertFalse(any(_reaches_retention(n) for n in ast.walk(harmless)))


def _reaches_retention(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name.startswith("memory.retention") for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module.startswith("memory.retention"):
            return True
        return module in ("memory", "") and any(
            alias.name in ("retention", "clear_module", "purge_expired") for alias in node.names
        )
    if isinstance(node, ast.Attribute):
        return node.attr in ("clear_module", "purge_expired")
    return False


class RetentionCommandLineTests(RetentionTestCase):
    def run_cli(self, *args: str, env: dict | None = None) -> tuple[int, str]:
        output = io.StringIO()
        with mock.patch.dict("os.environ", env or {}, clear=False), contextlib.redirect_stdout(
            output
        ), contextlib.redirect_stderr(output):
            code = retention_main(["--db", str(self.db_path), "--audit", str(self.audit.path), *args])
        return code, output.getvalue()

    def test_missing_database_is_not_created(self) -> None:
        missing = self.root / "absent.sqlite3"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = retention_main(["--db", str(missing), "run"])
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", output.getvalue())
        self.assertFalse(missing.exists())

    def test_run_once_reports_a_summary(self) -> None:
        code, output = self.run_cli("run", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn('"action": "purge_expired"', output)

    def test_clear_module_needs_approvers_then_previews_then_deletes(self) -> None:
        self.memory(None).record_proposal(LOGIN, proposal("Lock account"))
        args = ("clear-module", LOGIN, "--by", "qa-lead", "--reason", "rewritten")

        code, output = self.run_cli(*args, env={"QA_AGENT_APPROVERS": ""})
        self.assertEqual(code, 2)

        code, output = self.run_cli(*args, env={"QA_AGENT_APPROVERS": "qa-lead"})
        self.assertEqual(code, 0)
        self.assertIn("Preview only", output)
        self.assertEqual(self.remembered(LOGIN), 1)

        code, output = self.run_cli(*args, "--confirm", env={"QA_AGENT_APPROVERS": "qa-lead"})
        self.assertEqual(code, 0)
        self.assertEqual(self.remembered(LOGIN), 0)

        code, output = self.run_cli(
            "clear-module", BILLING, "--by", "intern", "--reason", "x", "--confirm",
            env={"QA_AGENT_APPROVERS": "qa-lead"},
        )
        self.assertEqual(code, 2)
        self.assertIn("Refused", output)


def _load_approve_cli():
    spec = importlib.util.spec_from_file_location("approve_cli", SCRIPTS / "approve_cli.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProposalRejectionPathTests(RetentionTestCase):
    """The human path that records a rejected test proposal (approve_cli.py)."""

    def setUp(self) -> None:
        super().setUp()
        self.cli = _load_approve_cli()
        self.data_dir = self.root / "data"
        self.env = {
            "QA_AGENT_APPROVERS": "qa-lead",
            "QA_AGENT_DATA_DIR": str(self.data_dir),
            "QA_AGENT_MEMORY_PATH": str(self.db_path),
        }
        self.record = self.memory(None).record_proposal(LOGIN, proposal("Lock account"))

    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        code = 0
        with mock.patch.dict("os.environ", self.env), contextlib.redirect_stdout(
            output
        ), contextlib.redirect_stderr(output):
            try:
                self.cli.main(list(args))
            except SystemExit as exit_:
                code = exit_.code or 0
        return code, output.getvalue()

    def audit_text(self) -> str:
        return (self.data_dir / "audit.log").read_text(encoding="utf-8")

    def test_proposals_lists_keys_for_a_module(self) -> None:
        code, output = self.run_cli("proposals", LOGIN)
        self.assertEqual(code, 0)
        self.assertIn(self.record.proposal_key, output)
        self.assertIn("proposed", output)

    def test_an_authorized_handle_records_the_rejection_and_audits_the_reason(self) -> None:
        code, output = self.run_cli(
            "reject-proposal", LOGIN, self.record.proposal_key,
            "--by", "qa-lead", "--reason", "duplicates an existing test",
        )

        self.assertEqual(code, 0)
        stored = self.memory(None).find(LOGIN, self.record.proposal_key)
        self.assertEqual(stored.status, ProposalMemoryStatus.REJECTED_BY_HUMAN)
        self.assertEqual(stored.rejected_by, "qa-lead")
        self.assertIn("proposal_rejected", self.audit_text())
        self.assertIn("duplicates an existing test", self.audit_text())

    def test_an_unauthorized_handle_is_refused_and_nothing_changes(self) -> None:
        code, output = self.run_cli(
            "reject-proposal", LOGIN, self.record.proposal_key, "--by", "intern", "--reason", "x"
        )

        self.assertEqual(code, 2)
        stored = self.memory(None).find(LOGIN, self.record.proposal_key)
        self.assertEqual(stored.status, ProposalMemoryStatus.PROPOSED)
        self.assertIn("proposal_rejection_refused", self.audit_text())

    def test_an_email_address_is_refused_as_a_handle(self) -> None:
        self.env["QA_AGENT_APPROVERS"] = "alice@example.com"
        code, output = self.run_cli(
            "reject-proposal", LOGIN, self.record.proposal_key,
            "--by", "alice@example.com", "--reason", "x",
        )

        self.assertEqual(code, 1)
        self.assertEqual(
            self.memory(None).find(LOGIN, self.record.proposal_key).status,
            ProposalMemoryStatus.PROPOSED,
        )

    def test_an_unknown_proposal_key_is_a_clean_error(self) -> None:
        code, output = self.run_cli(
            "reject-proposal", LOGIN, "0000000000000000", "--by", "qa-lead", "--reason", "x"
        )
        self.assertEqual(code, 1)
        self.assertIn("No memory record", output)


if __name__ == "__main__":
    unittest.main()
