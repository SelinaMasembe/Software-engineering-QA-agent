"""Human approval gate for approval-required tools (Member 5, Weeks 4-5).

``JSONApprovalGate`` implements ``orchestrator.router.ApprovalGate``. The
dispatcher calls ``check()`` before running any ``REQUIRES_APPROVAL`` tool
(``run_tests``, ``draft_issue``), and a human decides through
``scripts/approve_cli.py``, which shares the same JSON queue file.

How a request moves:

1. The first ``check()`` for a proposal creates a ``pending`` request keyed
   by a fingerprint of (session, action, validated arguments) and returns
   PENDING. Asking again while it is pending returns PENDING without creating
   a duplicate, so ``AgentLoop.resume`` can re-propose the same request.
2. An authorized human, who is not the requester, approves or denies it.
3. The next ``check()`` for the same fingerprint delivers that decision
   exactly once: APPROVED (the approval is consumed and cannot be replayed)
   or DENIED. A later identical proposal starts a new request.
4. A request nobody decides expires after ``request_ttl_seconds`` and is
   delivered as DENIED. The gate never approves by itself.

``wait_seconds`` (default 0) makes ``check()`` block for up to that long
waiting for a decision instead of returning PENDING straight away; when the
wait runs out the request expires. Demos and the two-terminal walkthrough use
it; the agent loop uses the default so it can pause and resume.

Every read-modify-write of the queue happens under an exclusive file lock, so
the agent process and the CLI process cannot overwrite each other's changes.
A corrupt queue raises ``ApprovalStoreError``, which the dispatcher reports as
APPROVAL_UNAVAILABLE: the gate fails closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Iterator

from models.types import Actor, TraceEntry
from orchestrator.router import (
    Action,
    ApprovalStatus,
    ApprovalVerdict,
)


class RequestState(str, Enum):
    """Lifecycle of one approval request in the queue file."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    id: str
    action_name: str
    description: str
    payload: dict[str, Any]
    requested_by: str
    requested_at: str
    status: str = RequestState.PENDING.value
    decided_by: str | None = None
    decided_at: str | None = None
    reason: str = ""
    session_id: str = ""
    fingerprint: str = ""
    expires_at: str | None = None
    consumed_at: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> "ApprovalRequest":
        if not isinstance(row, dict):
            raise ApprovalStoreError("Approval queue row is not an object.")
        known = {field.name for field in fields(cls)}
        try:
            return cls(**{key: value for key, value in row.items() if key in known})
        except TypeError as exc:
            raise ApprovalStoreError("Approval queue row is missing fields.") from exc


class ApprovalStoreError(RuntimeError):
    """The approval queue could not be read or is malformed."""


class ApprovalDenied(Exception):
    pass


class ApprovalTimeout(Exception):
    pass


class UnauthorizedApprover(Exception):
    pass


class SelfApprovalError(UnauthorizedApprover):
    """The requester tried to approve their own request."""


class JSONApprovalStore:
    """JSON file of approval requests, shared between processes."""

    def __init__(self, path: str = "data/approval_queue.json") -> None:
        self.path = path
        self.lock_path = f"{path}.lock"
        self._thread_lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with self._locked():
            if not os.path.exists(path):
                self._write({})

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock, _exclusive_file_lock(self.lock_path):
            yield

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                content = handle.read().strip()
            data = json.loads(content) if content else {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ApprovalStoreError("The approval queue could not be read.") from exc
        if not isinstance(data, dict):
            raise ApprovalStoreError("The approval queue must be a JSON object.")
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        directory = os.path.dirname(self.path) or "."
        fd, temporary = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def mutate(self, change: Callable[[dict[str, dict[str, Any]]], Any]) -> Any:
        """Run ``change`` on the queue under the lock and save the result.

        If ``change`` raises, nothing is written.
        """

        with self._locked():
            data = self._read()
            result = change(data)
            self._write(data)
        return result

    def create(self, request: ApprovalRequest) -> None:
        def change(data: dict[str, dict[str, Any]]) -> None:
            data[request.id] = asdict(request)

        self.mutate(change)

    def get(self, request_id: str) -> ApprovalRequest | None:
        with self._locked():
            row = self._read().get(request_id)
        return ApprovalRequest.from_row(row) if row else None

    def update(self, request: ApprovalRequest) -> None:
        def change(data: dict[str, dict[str, Any]]) -> None:
            if request.id not in data:
                raise KeyError(request.id)
            data[request.id] = asdict(request)

        self.mutate(change)

    def all(self) -> list[ApprovalRequest]:
        with self._locked():
            rows = list(self._read().values())
        return [ApprovalRequest.from_row(row) for row in rows]

    def list_pending(self, now: datetime | None = None) -> list[ApprovalRequest]:
        """Pending requests a human can still decide (not past expiry)."""

        now = now or _utc_now()
        return [
            request
            for request in self.all()
            if request.status == RequestState.PENDING.value
            and not _is_past(request.expires_at, now)
        ]


class AuditLogger:
    def __init__(self, path: str = "data/audit.log") -> None:
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def log(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        with self._lock, open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


class JSONApprovalGate:
    """Concrete implementation of orchestrator.router.ApprovalGate."""

    def __init__(
        self,
        store: JSONApprovalStore | None = None,
        audit: AuditLogger | None = None,
        authorized_approvers: set[str] | None = None,
        *,
        wait_seconds: float = 0,
        request_ttl_seconds: float = 900,
        poll_interval_seconds: float = 0.5,
        trace_sink: Any = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if wait_seconds < 0:
            raise ValueError("wait_seconds must not be negative.")
        if request_ttl_seconds <= 0:
            raise ValueError("request_ttl_seconds must be greater than zero.")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than zero.")
        if trace_sink is not None and not callable(getattr(trace_sink, "record", None)):
            raise ValueError("trace_sink must provide record(entry).")
        self.store = store or JSONApprovalStore()
        self.audit = audit or AuditLogger()
        self.authorized_approvers = set(authorized_approvers or ())
        self.wait_seconds = wait_seconds
        self.request_ttl_seconds = request_ttl_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.trace_sink = trace_sink
        self._clock = clock or _utc_now

    def check(self, *, action, arguments, context) -> ApprovalVerdict:
        action_name = Action(action).value
        payload = _plain(arguments)
        fingerprint = request_fingerprint(context.session_id, action_name, payload)

        status = self.store.mutate(
            lambda data: self._step(data, action_name, payload, fingerprint, context)
        )
        if status is not ApprovalStatus.PENDING or self.wait_seconds == 0:
            return ApprovalVerdict(status)

        deadline = time.monotonic() + self.wait_seconds
        while time.monotonic() < deadline:
            time.sleep(self.poll_interval_seconds)
            status = self.store.mutate(
                lambda data: self._step(data, action_name, payload, fingerprint, context)
            )
            if status is not ApprovalStatus.PENDING:
                return ApprovalVerdict(status)

        # The wait ran out: expire the request and deliver it as a denial.
        status = self.store.mutate(
            lambda data: self._step(
                data, action_name, payload, fingerprint, context, force_expire=True
            )
        )
        return ApprovalVerdict(status)

    def _step(
        self,
        data: dict[str, dict[str, Any]],
        action_name: str,
        payload: dict[str, Any],
        fingerprint: str,
        context: Any,
        *,
        force_expire: bool = False,
    ) -> ApprovalStatus:
        """One locked look at the queue for this fingerprint."""

        now = self._clock()
        self._expire_stale(data, now, force_fingerprint=fingerprint if force_expire else None)

        matching = [
            ApprovalRequest.from_row(row)
            for row in data.values()
            if isinstance(row, dict)
            and row.get("fingerprint") == fingerprint
            and row.get("consumed_at") is None
        ]
        decided = [r for r in matching if r.status != RequestState.PENDING.value]
        if decided:
            request = min(decided, key=lambda r: r.requested_at)
            return self._deliver(data, request, now, context)
        if any(r.status == RequestState.PENDING.value for r in matching):
            return ApprovalStatus.PENDING

        request = ApprovalRequest(
            id=str(uuid.uuid4()),
            action_name=action_name,
            description=f"Approval required for {action_name}",
            payload=payload,
            requested_by=context.actor_id,
            requested_at=now.isoformat(),
            session_id=context.session_id,
            fingerprint=fingerprint,
            expires_at=(now + timedelta(seconds=self.request_ttl_seconds)).isoformat(),
        )
        data[request.id] = asdict(request)
        self.audit.log(
            "approval_requested",
            request_id=request.id,
            action=action_name,
            session_id=context.session_id,
            requested_by=request.requested_by,
            fingerprint=fingerprint,
            payload=payload,
        )
        return ApprovalStatus.PENDING

    def _deliver(
        self,
        data: dict[str, dict[str, Any]],
        request: ApprovalRequest,
        now: datetime,
        context: Any,
    ) -> ApprovalStatus:
        """Hand one decided request to the dispatcher and mark it used."""

        request.consumed_at = now.isoformat()
        short_id = request.id[:8]

        if (
            request.status == RequestState.APPROVED.value
            and request.decided_by not in self.authorized_approvers
        ):
            # The queue says approved, but not by someone this gate trusts
            # (e.g. a hand-edited file or a different approver list).
            request.status = RequestState.DENIED.value
            request.reason = "Approver is not authorized for this gate."
            self.audit.log(
                "approval_rejected_unauthorized",
                request_id=request.id,
                decided_by=request.decided_by,
            )

        if request.status == RequestState.APPROVED.value:
            self._trace(
                context,
                Actor.HUMAN,
                "approval_granted",
                f"request={short_id}; action={request.action_name}; "
                f"approver={request.decided_by}",
            )
            self.audit.log(
                "approval_consumed",
                request_id=request.id,
                action=request.action_name,
                approved_by=request.decided_by,
            )
            data[request.id] = asdict(request)
            return ApprovalStatus.APPROVED

        if request.status == RequestState.EXPIRED.value:
            self._trace(
                context,
                Actor.DETERMINISTIC,
                "approval_expired",
                f"request={short_id}; action={request.action_name}",
            )
        else:
            self._trace(
                context,
                Actor.HUMAN,
                "approval_denied",
                f"request={short_id}; action={request.action_name}; "
                f"approver={request.decided_by}",
            )
        self.audit.log(
            "action_blocked",
            request_id=request.id,
            action=request.action_name,
            status=request.status,
        )
        data[request.id] = asdict(request)
        return ApprovalStatus.DENIED

    def _expire_stale(
        self,
        data: dict[str, dict[str, Any]],
        now: datetime,
        *,
        force_fingerprint: str | None = None,
    ) -> None:
        for request_id, row in data.items():
            if not isinstance(row, dict) or row.get("status") != RequestState.PENDING.value:
                continue
            forced = force_fingerprint is not None and row.get("fingerprint") == force_fingerprint
            if forced or _is_past(row.get("expires_at"), now):
                row["status"] = RequestState.EXPIRED.value
                row["reason"] = "Approval timeout."
                row["decided_at"] = now.isoformat()
                self.audit.log("approval_expired", request_id=request_id)

    def _trace(self, context: Any, actor: Actor, action: str, detail: str) -> None:
        if self.trace_sink is None:
            return
        self.trace_sink.record(
            TraceEntry(
                session_id=context.session_id,
                actor=actor,
                action=action,
                detail=detail,
                timestamp=self._clock(),
            )
        )

    def decide(
        self,
        request_id: str,
        *,
        approve: bool,
        decided_by: str,
        reason: str = "",
    ) -> ApprovalRequest:
        def change(data: dict[str, dict[str, Any]]) -> ApprovalRequest:
            now = self._clock()
            self._expire_stale(data, now)
            row = data.get(request_id)
            if row is None:
                raise KeyError(request_id)
            request = ApprovalRequest.from_row(row)
            if request.status == RequestState.EXPIRED.value:
                raise ValueError("Approval request has expired.")
            if request.status != RequestState.PENDING.value:
                raise ValueError("Approval request has already been decided.")
            if decided_by not in self.authorized_approvers:
                # Audited and refused, but the request stays pending so a
                # real approver can still decide it.
                self.audit.log(
                    "decision_rejected_unauthorized",
                    request_id=request_id,
                    attempted_by=decided_by,
                )
                raise UnauthorizedApprover(decided_by)
            if decided_by == request.requested_by:
                self.audit.log(
                    "decision_rejected_self_approval",
                    request_id=request_id,
                    attempted_by=decided_by,
                )
                raise SelfApprovalError(decided_by)

            request.status = (
                RequestState.APPROVED.value if approve else RequestState.DENIED.value
            )
            request.decided_by = decided_by
            request.decided_at = now.isoformat()
            request.reason = reason
            data[request_id] = asdict(request)
            self.audit.log(
                "decision_recorded",
                request_id=request_id,
                status=request.status,
                decided_by=decided_by,
                reason=reason,
            )
            return request

        return self.store.mutate(change)


def request_fingerprint(session_id: str, action_name: str, payload: Any) -> str:
    """Stable SHA-256 of what is being approved, used to match re-proposals."""

    canonical = json.dumps(
        {"session_id": session_id, "action": action_name, "arguments": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plain(value: Any) -> Any:
    """Copy validated arguments into plain JSON data (tuples become lists)."""

    return json.loads(json.dumps(value, default=str))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_past(timestamp: Any, now: datetime) -> bool:
    if not isinstance(timestamp, str):
        return False
    try:
        return datetime.fromisoformat(timestamp) <= now
    except ValueError:
        return False


@contextmanager
def _exclusive_file_lock(path: str) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` across processes."""

    with open(path, "a+b") as handle:
        if os.name == "nt":  # pragma: no cover - exercised on Windows only
            import msvcrt

            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
