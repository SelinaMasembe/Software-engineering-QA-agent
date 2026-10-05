"""Persistent-memory storage and explicit workflow state.

This module is owned by Week 6 Member 2.  The first section models the
lifecycle of one agent session.  The storage backend is added separately so
the state rules can be reviewed without defining Member 1's memory-record
schema or Member 3's policy for choosing and using memories.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class SessionPhase(str, Enum):
    """Durable lifecycle phase for one bounded agent session."""

    CREATED = "created"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    HALTED = "halted"
    FAILED = "failed"


class StateTransitionError(ValueError):
    """A requested session-state transition violates the lifecycle."""


_TERMINAL_PHASES = frozenset(
    {SessionPhase.COMPLETED, SessionPhase.HALTED, SessionPhase.FAILED}
)

_ALLOWED_TRANSITIONS = {
    SessionPhase.CREATED: frozenset(
        {SessionPhase.RUNNING, SessionPhase.HALTED, SessionPhase.FAILED}
    ),
    SessionPhase.RUNNING: frozenset(
        {
            SessionPhase.AWAITING_APPROVAL,
            SessionPhase.COMPLETED,
            SessionPhase.HALTED,
            SessionPhase.FAILED,
        }
    ),
    SessionPhase.AWAITING_APPROVAL: frozenset(
        {SessionPhase.RUNNING, SessionPhase.HALTED, SessionPhase.FAILED}
    ),
    SessionPhase.COMPLETED: frozenset(),
    SessionPhase.HALTED: frozenset(),
    SessionPhase.FAILED: frozenset(),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware datetime.")
    if value.utcoffset() is None:
        raise ValueError(f"{label} must have a valid UTC offset.")


def _clean_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class SessionState:
    """Immutable, persistable state of one agent workflow.

    ``pending_approval_id`` records only that a human decision is pending.  It
    is not an approval decision and therefore cannot authorize an action.
    Approval remains the responsibility of the orchestration approval gate.
    """

    session_id: str
    phase: SessionPhase
    iteration_count: int
    revision: int
    created_at: datetime
    updated_at: datetime
    pending_approval_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "session_id", _clean_identifier(self.session_id, "Session identifier")
        )
        if not isinstance(self.phase, SessionPhase):
            raise ValueError("Session phase must be a SessionPhase value.")
        for value, label in (
            (self.iteration_count, "Iteration count"),
            (self.revision, "Revision"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be a non-negative integer.")
        _require_aware(self.created_at, "Created timestamp")
        _require_aware(self.updated_at, "Updated timestamp")
        if self.updated_at < self.created_at:
            raise ValueError("Updated timestamp cannot precede the created timestamp.")

        if self.phase is SessionPhase.AWAITING_APPROVAL:
            cleaned = _clean_identifier(
                self.pending_approval_id, "Pending approval identifier"
            )
            object.__setattr__(self, "pending_approval_id", cleaned)
        elif self.pending_approval_id is not None:
            raise ValueError(
                "A pending approval identifier is allowed only while awaiting approval."
            )

    @classmethod
    def create(cls, session_id: str, *, at: datetime | None = None) -> SessionState:
        """Create the initial state for a new session."""

        timestamp = _utc_now() if at is None else at
        return cls(
            session_id=session_id,
            phase=SessionPhase.CREATED,
            iteration_count=0,
            revision=0,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @property
    def is_terminal(self) -> bool:
        """Whether the workflow has reached an irreversible end state."""

        return self.phase in _TERMINAL_PHASES

    def transition(
        self,
        phase: SessionPhase,
        *,
        at: datetime | None = None,
        iteration_count: int | None = None,
        pending_approval_id: str | None = None,
    ) -> SessionState:
        """Return the next legal lifecycle state.

        Iterations may stay unchanged or increase, but can never be rewound.
        Entering ``AWAITING_APPROVAL`` requires the approval request identifier;
        leaving it removes that identifier.  This method never records an
        approval outcome or grants permission to execute a tool.
        """

        try:
            target = SessionPhase(phase)
        except (TypeError, ValueError) as exc:
            raise StateTransitionError("The target session phase is invalid.") from exc
        if target not in _ALLOWED_TRANSITIONS[self.phase]:
            raise StateTransitionError(
                f"Session cannot transition from {self.phase.value} to {target.value}."
            )

        timestamp = _utc_now() if at is None else at
        _require_aware(timestamp, "Transition timestamp")
        if timestamp < self.updated_at:
            raise StateTransitionError(
                "Transition timestamp cannot precede the current state timestamp."
            )

        next_iterations = (
            self.iteration_count if iteration_count is None else iteration_count
        )
        if (
            isinstance(next_iterations, bool)
            or not isinstance(next_iterations, int)
            or next_iterations < self.iteration_count
        ):
            raise StateTransitionError(
                "A transition cannot reduce the completed iteration count."
            )

        return SessionState(
            session_id=self.session_id,
            phase=target,
            iteration_count=next_iterations,
            revision=self.revision + 1,
            created_at=self.created_at,
            updated_at=timestamp,
            pending_approval_id=pending_approval_id,
        )

    def record_iteration(self, *, at: datetime | None = None) -> SessionState:
        """Return a running state after one more completed loop iteration."""

        if self.phase is not SessionPhase.RUNNING:
            raise StateTransitionError(
                "Iterations can be recorded only while the session is running."
            )
        timestamp = _utc_now() if at is None else at
        _require_aware(timestamp, "Iteration timestamp")
        if timestamp < self.updated_at:
            raise StateTransitionError(
                "Iteration timestamp cannot precede the current state timestamp."
            )
        return SessionState(
            session_id=self.session_id,
            phase=self.phase,
            iteration_count=self.iteration_count + 1,
            revision=self.revision + 1,
            created_at=self.created_at,
            updated_at=timestamp,
        )
