"""Persistent-memory storage and explicit workflow state.

This module is owned by Week 6 Member 2.  The first section models the
lifecycle of one agent session.  The storage backend is added separately so
the state rules can be reviewed without defining Member 1's memory-record
schema or Member 3's policy for choosing and using memories.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


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


class StoreConflictError(RuntimeError):
    """A create or revision-checked update conflicts with stored data."""


class StoreClosedError(RuntimeError):
    """An operation was attempted after the store was closed."""


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


@dataclass(frozen=True)
class StoredMemory:
    """Storage envelope around one schema-owned JSON memory document.

    The keys inside ``document`` belong to Member 1's memory-record schema.
    This envelope adds only the identifiers, timestamps and revision needed
    for safe persistence.  It deliberately contains no memory-selection or
    decision-making policy.
    """

    namespace: str
    record_id: str
    document: Mapping[str, Any]
    revision: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_records (
    namespace TEXT NOT NULL,
    record_id TEXT NOT NULL,
    document_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    PRIMARY KEY (namespace, record_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_expiry
ON memory_records (expires_at)
WHERE expires_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS session_states (
    session_id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    iteration_count INTEGER NOT NULL CHECK (iteration_count >= 0),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    pending_approval_id TEXT
);
"""


class MemoryStore:
    """SQLite persistence for memory documents and explicit session state.

    Memory documents are opaque JSON objects.  Callers must validate them
    against ``memory.schema`` before calling this layer.  Writes use
    optimistic revisions so two processes cannot silently overwrite each
    other.  The store exposes expired records for Member 5's retention job,
    but does not implement or schedule retention itself.
    """

    def __init__(self, path: str | Path) -> None:
        if isinstance(path, Path):
            raw_path = str(path)
        elif isinstance(path, str) and path.strip():
            raw_path = path
        else:
            raise ValueError("Memory store path must be a non-empty path.")

        self.path = Path(raw_path) if raw_path != ":memory:" else Path(raw_path)
        if raw_path != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(raw_path)
        self._connection.row_factory = sqlite3.Row
        self._closed = False
        with self._connection:
            self._connection.executescript(_SCHEMA)
            self._connection.execute("PRAGMA user_version = 1")
        if raw_path != ":memory:":
            os.chmod(self.path, 0o600)

    def close(self) -> None:
        """Close the database connection.  Calling this twice is safe."""

        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> MemoryStore:
        self._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def put(
        self,
        namespace: str,
        record_id: str,
        document: Mapping[str, Any],
        *,
        expires_at: datetime | None,
        expected_revision: int | None = None,
        at: datetime | None = None,
    ) -> StoredMemory:
        """Create or revision-check an opaque memory document.

        Omit ``expected_revision`` to create a new record.  Supply the current
        revision to update it.  This explicit distinction prevents accidental
        last-writer-wins overwrites.
        """

        self._require_open()
        clean_namespace = _clean_identifier(namespace, "Memory namespace")
        clean_record_id = _clean_identifier(record_id, "Memory record identifier")
        encoded, detached = _encode_document(document)
        timestamp = _utc_now() if at is None else at
        _require_aware(timestamp, "Memory timestamp")
        timestamp = timestamp.astimezone(timezone.utc)
        if expires_at is not None:
            _require_aware(expires_at, "Memory expiry timestamp")
            expires_at = expires_at.astimezone(timezone.utc)
            if expires_at <= timestamp:
                raise ValueError("Memory expiry timestamp must be after its update time.")

        if expected_revision is None:
            try:
                with self._connection:
                    self._connection.execute(
                        """
                        INSERT INTO memory_records (
                            namespace, record_id, document_json, revision,
                            created_at, updated_at, expires_at
                        ) VALUES (?, ?, ?, 0, ?, ?, ?)
                        """,
                        (
                            clean_namespace,
                            clean_record_id,
                            encoded,
                            _to_text(timestamp),
                            _to_text(timestamp),
                            _to_text(expires_at) if expires_at else None,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise StoreConflictError(
                    "A memory record with this namespace and identifier already exists."
                ) from exc
            return StoredMemory(
                namespace=clean_namespace,
                record_id=clean_record_id,
                document=detached,
                revision=0,
                created_at=timestamp,
                updated_at=timestamp,
                expires_at=expires_at,
            )

        _require_revision(expected_revision, "Expected memory revision")
        current = self.get(clean_namespace, clean_record_id)
        if current is None or current.revision != expected_revision:
            raise StoreConflictError("The memory record revision is stale or missing.")
        if timestamp < current.updated_at:
            raise ValueError("Memory update time cannot move backwards.")
        next_revision = expected_revision + 1
        with self._connection:
            changed = self._connection.execute(
                """
                UPDATE memory_records
                SET document_json = ?, revision = ?, updated_at = ?, expires_at = ?
                WHERE namespace = ? AND record_id = ? AND revision = ?
                """,
                (
                    encoded,
                    next_revision,
                    _to_text(timestamp),
                    _to_text(expires_at) if expires_at else None,
                    clean_namespace,
                    clean_record_id,
                    expected_revision,
                ),
            ).rowcount
        if changed != 1:
            raise StoreConflictError("The memory record changed during the update.")
        return StoredMemory(
            namespace=clean_namespace,
            record_id=clean_record_id,
            document=detached,
            revision=next_revision,
            created_at=current.created_at,
            updated_at=timestamp,
            expires_at=expires_at,
        )

    def get(self, namespace: str, record_id: str) -> StoredMemory | None:
        """Load one memory document, or return ``None`` when it is absent."""

        self._require_open()
        row = self._connection.execute(
            """
            SELECT namespace, record_id, document_json, revision,
                   created_at, updated_at, expires_at
            FROM memory_records
            WHERE namespace = ? AND record_id = ?
            """,
            (
                _clean_identifier(namespace, "Memory namespace"),
                _clean_identifier(record_id, "Memory record identifier"),
            ),
        ).fetchone()
        return None if row is None else _stored_memory(row)

    def list(self, namespace: str, *, limit: int = 100) -> tuple[StoredMemory, ...]:
        """List a bounded namespace, most recently updated first."""

        self._require_open()
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Memory list limit must be between 1 and 1000.")
        rows = self._connection.execute(
            """
            SELECT namespace, record_id, document_json, revision,
                   created_at, updated_at, expires_at
            FROM memory_records
            WHERE namespace = ?
            ORDER BY updated_at DESC, record_id ASC
            LIMIT ?
            """,
            (_clean_identifier(namespace, "Memory namespace"), limit),
        ).fetchall()
        return tuple(_stored_memory(row) for row in rows)

    def list_expired(
        self, *, before: datetime, limit: int = 100
    ) -> tuple[StoredMemory, ...]:
        """Return retention candidates without deleting them."""

        self._require_open()
        _require_aware(before, "Retention cutoff")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Expired-memory limit must be between 1 and 1000.")
        rows = self._connection.execute(
            """
            SELECT namespace, record_id, document_json, revision,
                   created_at, updated_at, expires_at
            FROM memory_records
            WHERE expires_at IS NOT NULL AND expires_at <= ?
            ORDER BY expires_at ASC, namespace ASC, record_id ASC
            LIMIT ?
            """,
            (_to_text(before.astimezone(timezone.utc)), limit),
        ).fetchall()
        return tuple(_stored_memory(row) for row in rows)

    def delete(
        self,
        namespace: str,
        record_id: str,
        *,
        expected_revision: int | None = None,
    ) -> bool:
        """Delete one record, optionally only at the expected revision."""

        self._require_open()
        clean_namespace = _clean_identifier(namespace, "Memory namespace")
        clean_record_id = _clean_identifier(record_id, "Memory record identifier")
        if expected_revision is not None:
            _require_revision(expected_revision, "Expected memory revision")
        current = self.get(clean_namespace, clean_record_id)
        if current is None:
            return False
        if expected_revision is not None and current.revision != expected_revision:
            raise StoreConflictError("The memory record revision is stale.")
        query = "DELETE FROM memory_records WHERE namespace = ? AND record_id = ?"
        parameters: tuple[Any, ...] = (clean_namespace, clean_record_id)
        if expected_revision is not None:
            query += " AND revision = ?"
            parameters = (*parameters, expected_revision)
        with self._connection:
            changed = self._connection.execute(query, parameters).rowcount
        if changed != 1:
            raise StoreConflictError("The memory record changed during deletion.")
        return True

    def create_session(self, state: SessionState) -> None:
        """Persist a newly created session state."""

        self._require_open()
        if not isinstance(state, SessionState):
            raise TypeError("Session state must be a SessionState.")
        if state.phase is not SessionPhase.CREATED or state.revision != 0:
            raise ValueError("Only a new CREATED session at revision zero can be inserted.")
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO session_states (
                        session_id, phase, iteration_count, revision,
                        created_at, updated_at, pending_approval_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    _state_parameters(state),
                )
        except sqlite3.IntegrityError as exc:
            raise StoreConflictError("This session already exists.") from exc

    def load_session(self, session_id: str) -> SessionState | None:
        """Load one persisted session state."""

        self._require_open()
        row = self._connection.execute(
            """
            SELECT session_id, phase, iteration_count, revision,
                   created_at, updated_at, pending_approval_id
            FROM session_states WHERE session_id = ?
            """,
            (_clean_identifier(session_id, "Session identifier"),),
        ).fetchone()
        if row is None:
            return None
        return SessionState(
            session_id=row["session_id"],
            phase=SessionPhase(row["phase"]),
            iteration_count=row["iteration_count"],
            revision=row["revision"],
            created_at=_from_text(row["created_at"]),
            updated_at=_from_text(row["updated_at"]),
            pending_approval_id=row["pending_approval_id"],
        )

    def save_session(self, state: SessionState, *, expected_revision: int) -> None:
        """Persist the next immutable session state with a revision check."""

        self._require_open()
        if not isinstance(state, SessionState):
            raise TypeError("Session state must be a SessionState.")
        _require_revision(expected_revision, "Expected session revision")
        if state.revision != expected_revision + 1:
            raise ValueError("Session state must be exactly one revision newer.")
        current = self.load_session(state.session_id)
        if current is None or current.revision != expected_revision:
            raise StoreConflictError("The session state revision is stale or missing.")
        if state.created_at != current.created_at:
            raise ValueError("Session creation time cannot be changed.")
        if state.updated_at < current.updated_at:
            raise ValueError("Session update time cannot move backwards.")
        if state.phase is current.phase:
            if not (
                state.phase is SessionPhase.RUNNING
                and state.iteration_count == current.iteration_count + 1
            ):
                raise ValueError("Only a running session may record an iteration.")
        elif state.phase not in _ALLOWED_TRANSITIONS[current.phase]:
            raise StateTransitionError(
                f"Session cannot transition from {current.phase.value} "
                f"to {state.phase.value}."
            )
        elif state.iteration_count < current.iteration_count:
            raise ValueError("Session iteration count cannot move backwards.")
        with self._connection:
            changed = self._connection.execute(
                """
                UPDATE session_states
                SET phase = ?, iteration_count = ?, revision = ?,
                    updated_at = ?, pending_approval_id = ?
                WHERE session_id = ? AND revision = ?
                """,
                (
                    state.phase.value,
                    state.iteration_count,
                    state.revision,
                    _to_text(state.updated_at),
                    state.pending_approval_id,
                    state.session_id,
                    expected_revision,
                ),
            ).rowcount
        if changed != 1:
            raise StoreConflictError("The session state revision is stale or missing.")

    def _require_open(self) -> None:
        if self._closed:
            raise StoreClosedError("The memory store is closed.")


def _require_revision(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer.")


def _check_json(value: Any, path: str = "document") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number.")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key.")
            _check_json(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_json(item, f"{path}[{index}]")
        return
    raise ValueError(f"{path} contains a value that is not JSON-compatible.")


def _encode_document(document: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(document, Mapping):
        raise ValueError("Memory document must be a JSON object.")
    _check_json(document)
    encoded = json.dumps(
        document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    detached = json.loads(encoded)
    return encoded, detached


def _to_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _from_text(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    _require_aware(parsed, "Stored timestamp")
    return parsed


def _stored_memory(row: sqlite3.Row) -> StoredMemory:
    return StoredMemory(
        namespace=row["namespace"],
        record_id=row["record_id"],
        document=json.loads(row["document_json"]),
        revision=row["revision"],
        created_at=_from_text(row["created_at"]),
        updated_at=_from_text(row["updated_at"]),
        expires_at=_from_text(row["expires_at"]) if row["expires_at"] else None,
    )


def _state_parameters(state: SessionState) -> tuple[Any, ...]:
    return (
        state.session_id,
        state.phase.value,
        state.iteration_count,
        state.revision,
        _to_text(state.created_at),
        _to_text(state.updated_at),
        state.pending_approval_id,
    )
