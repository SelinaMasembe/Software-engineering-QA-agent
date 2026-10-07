"""Unit tests for Member 2's schema-neutral persistent memory store."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory import (
    MemoryStore,
    SessionPhase,
    SessionState,
    StateTransitionError,
    StoreClosedError,
    StoreConflictError,
)


START = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


class MemoryStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "memory.sqlite3"
        self.store = MemoryStore(self.database)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()


class MemoryDocumentTests(MemoryStoreTestCase):
    def test_document_survives_store_reopen(self) -> None:
        saved = self.store.put(
            "proposal-history",
            "record-1",
            {"module": "auth", "status": "proposed", "tags": ["login"]},
            expires_at=START + timedelta(days=30),
            at=START,
        )
        self.store.close()
        self.store = MemoryStore(self.database)

        loaded = self.store.get("proposal-history", "record-1")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.document, saved.document)
        self.assertEqual(loaded.revision, 0)
        self.assertEqual(loaded.expires_at, START + timedelta(days=30))

    def test_namespaces_keep_equal_identifiers_separate(self) -> None:
        self.store.put("one", "same-id", {"value": 1}, expires_at=None, at=START)
        self.store.put("two", "same-id", {"value": 2}, expires_at=None, at=START)

        self.assertEqual(self.store.get("one", "same-id").document["value"], 1)
        self.assertEqual(self.store.get("two", "same-id").document["value"], 2)

    def test_update_requires_the_current_revision(self) -> None:
        self.store.put("history", "record-1", {"value": 1}, expires_at=None, at=START)
        updated = self.store.put(
            "history",
            "record-1",
            {"value": 2},
            expires_at=None,
            expected_revision=0,
            at=START + timedelta(seconds=1),
        )

        self.assertEqual(updated.revision, 1)
        with self.assertRaises(StoreConflictError):
            self.store.put(
                "history",
                "record-1",
                {"value": 3},
                expires_at=None,
                expected_revision=0,
                at=START + timedelta(seconds=2),
            )

    def test_create_never_silently_overwrites(self) -> None:
        self.store.put("history", "record-1", {"value": 1}, expires_at=None, at=START)

        with self.assertRaises(StoreConflictError):
            self.store.put(
                "history", "record-1", {"value": 2}, expires_at=None, at=START
            )

    def test_list_is_bounded_and_expiry_query_does_not_delete(self) -> None:
        self.store.put(
            "history",
            "expired",
            {"value": 1},
            expires_at=START + timedelta(days=1),
            at=START,
        )
        self.store.put(
            "history",
            "active",
            {"value": 2},
            expires_at=START + timedelta(days=10),
            at=START,
        )

        expired = self.store.list_expired(before=START + timedelta(days=2), limit=10)

        self.assertEqual([record.record_id for record in expired], ["expired"])
        self.assertEqual(len(self.store.list("history", limit=1)), 1)
        self.assertIsNotNone(self.store.get("history", "expired"))

    def test_delete_can_be_revision_checked(self) -> None:
        self.store.put("history", "record-1", {"value": 1}, expires_at=None, at=START)

        with self.assertRaises(StoreConflictError):
            self.store.delete("history", "record-1", expected_revision=1)
        self.assertTrue(
            self.store.delete("history", "record-1", expected_revision=0)
        )
        self.assertFalse(self.store.delete("history", "record-1"))

    def test_only_json_objects_are_accepted(self) -> None:
        with self.assertRaises(ValueError):
            self.store.put("history", "one", ["not", "an", "object"], expires_at=None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.store.put(
                "history", "two", {"bad": float("nan")}, expires_at=None
            )

    def test_database_permissions_are_owner_only(self) -> None:
        self.assertEqual(os.stat(self.database).st_mode & 0o777, 0o600)


class SessionPersistenceTests(MemoryStoreTestCase):
    def test_session_round_trips_through_each_revision(self) -> None:
        created = SessionState.create("session-1", at=START)
        self.store.create_session(created)
        running = created.transition(SessionPhase.RUNNING, at=START)
        self.store.save_session(running, expected_revision=0)
        paused = running.transition(
            SessionPhase.AWAITING_APPROVAL,
            at=START + timedelta(seconds=1),
            pending_approval_id="approval-1",
        )
        self.store.save_session(paused, expected_revision=1)

        self.assertEqual(self.store.load_session("session-1"), paused)

    def test_duplicate_and_stale_session_writes_are_rejected(self) -> None:
        created = SessionState.create("session-1", at=START)
        self.store.create_session(created)
        with self.assertRaises(StoreConflictError):
            self.store.create_session(created)

        running = created.transition(SessionPhase.RUNNING, at=START)
        self.store.save_session(running, expected_revision=0)
        stale_failure = created.transition(SessionPhase.FAILED, at=START)
        with self.assertRaises(StoreConflictError):
            self.store.save_session(stale_failure, expected_revision=0)

    def test_store_rechecks_lifecycle_instead_of_trusting_a_crafted_state(self) -> None:
        created = SessionState.create("session-1", at=START)
        self.store.create_session(created)
        crafted = SessionState(
            session_id="session-1",
            phase=SessionPhase.COMPLETED,
            iteration_count=0,
            revision=1,
            created_at=START,
            updated_at=START,
        )

        with self.assertRaises(StateTransitionError):
            self.store.save_session(crafted, expected_revision=0)
        self.assertEqual(self.store.load_session("session-1"), created)

    def test_closed_store_rejects_operations(self) -> None:
        self.store.close()

        with self.assertRaises(StoreClosedError):
            self.store.load_session("session-1")


if __name__ == "__main__":
    unittest.main()
