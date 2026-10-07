"""Unit tests for Member 2's explicit Week 6 session-state model."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from memory import SessionPhase, SessionState, StateTransitionError


START = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


class SessionStateLifecycleTests(unittest.TestCase):
    def test_running_session_can_pause_resume_and_complete(self) -> None:
        created = SessionState.create("session-1", at=START)
        running = created.transition(SessionPhase.RUNNING, at=START)
        after_turn = running.record_iteration(at=START + timedelta(seconds=1))
        paused = after_turn.transition(
            SessionPhase.AWAITING_APPROVAL,
            at=START + timedelta(seconds=2),
            pending_approval_id="approval-1",
        )
        resumed = paused.transition(
            SessionPhase.RUNNING, at=START + timedelta(seconds=3)
        )
        completed = resumed.transition(
            SessionPhase.COMPLETED,
            at=START + timedelta(seconds=4),
            iteration_count=2,
        )

        self.assertEqual(created.revision, 0)
        self.assertEqual(completed.phase, SessionPhase.COMPLETED)
        self.assertEqual(completed.iteration_count, 2)
        self.assertEqual(completed.revision, 5)
        self.assertIsNone(resumed.pending_approval_id)
        self.assertTrue(completed.is_terminal)

    def test_created_session_may_halt_before_first_iteration(self) -> None:
        halted = SessionState.create("session-1", at=START).transition(
            SessionPhase.HALTED, at=START
        )

        self.assertEqual(halted.phase, SessionPhase.HALTED)
        self.assertEqual(halted.iteration_count, 0)

    def test_failed_session_is_terminal(self) -> None:
        failed = SessionState.create("session-1", at=START).transition(
            SessionPhase.FAILED, at=START
        )

        with self.assertRaises(StateTransitionError):
            failed.transition(SessionPhase.RUNNING, at=START)


class SessionStateInvariantTests(unittest.TestCase):
    def test_identifiers_and_counts_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            SessionState.create(" ", at=START)
        with self.assertRaises(ValueError):
            SessionState(
                session_id="session-1",
                phase=SessionPhase.CREATED,
                iteration_count=-1,
                revision=0,
                created_at=START,
                updated_at=START,
            )

    def test_timestamps_must_be_aware_and_monotonic(self) -> None:
        with self.assertRaises(ValueError):
            SessionState.create("session-1", at=datetime(2026, 10, 5, 8, 0))

        running = SessionState.create("session-1", at=START).transition(
            SessionPhase.RUNNING, at=START
        )
        with self.assertRaises(StateTransitionError):
            running.record_iteration(at=START - timedelta(seconds=1))

    def test_approval_identifier_is_required_exactly_while_paused(self) -> None:
        running = SessionState.create("session-1", at=START).transition(
            SessionPhase.RUNNING, at=START
        )
        with self.assertRaises(ValueError):
            running.transition(SessionPhase.AWAITING_APPROVAL, at=START)
        with self.assertRaises(ValueError):
            running.transition(
                SessionPhase.COMPLETED,
                at=START,
                pending_approval_id="approval-1",
            )

    def test_illegal_skip_and_iteration_rewind_are_rejected(self) -> None:
        created = SessionState.create("session-1", at=START)
        with self.assertRaises(StateTransitionError):
            created.transition(SessionPhase.COMPLETED, at=START)

        running = created.transition(
            SessionPhase.RUNNING, at=START, iteration_count=2
        )
        with self.assertRaises(StateTransitionError):
            running.transition(
                SessionPhase.HALTED, at=START, iteration_count=1
            )

    def test_iterations_are_recorded_only_while_running(self) -> None:
        created = SessionState.create("session-1", at=START)

        with self.assertRaises(StateTransitionError):
            created.record_iteration(at=START)


if __name__ == "__main__":
    unittest.main()
