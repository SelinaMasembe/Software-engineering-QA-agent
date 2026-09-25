from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from orchestration.tool_dispatcher import (
    Action,
    ApprovalStatus,
    ApprovalVerdict,
)


@dataclass
class ApprovalRequest:
    id: str
    action_name: str
    description: str
    payload: dict[str, Any]
    requested_by: str
    requested_at: str
    status: str = "pending"
    decided_by: str | None = None
    decided_at: str | None = None
    reason: str = ""


class ApprovalDenied(Exception):
    pass


class ApprovalTimeout(Exception):
    pass


class UnauthorizedApprover(Exception):
    pass


class JSONApprovalStore:
    def __init__(self, path: str = "data/approval_queue.json") -> None:
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            self._write({})

    def _read(self) -> dict[str, dict[str, Any]]:
        with open(self.path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
        return json.loads(content) if content else {}

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

    def create(self, request: ApprovalRequest) -> None:
        with self._lock:
            data = self._read()
            data[request.id] = asdict(request)
            self._write(data)

    def get(self, request_id: str) -> ApprovalRequest | None:
        with self._lock:
            row = self._read().get(request_id)
        return ApprovalRequest(**row) if row else None

    def update(self, request: ApprovalRequest) -> None:
        with self._lock:
            data = self._read()
            if request.id not in data:
                raise KeyError(request.id)
            data[request.id] = asdict(request)
            self._write(data)

    def list_pending(self) -> list[ApprovalRequest]:
        with self._lock:
            rows = self._read().values()
        return [
            ApprovalRequest(**row)
            for row in rows
            if row["status"] == ApprovalStatus.PENDING.value
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
    """Concrete implementation of orchestration.tool_dispatcher.ApprovalGate."""

    def __init__(
        self,
        store: JSONApprovalStore | None = None,
        audit: AuditLogger | None = None,
        authorized_approvers: set[str] | None = None,
        timeout_seconds: float = 120,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self.store = store or JSONApprovalStore()
        self.audit = audit or AuditLogger()
        self.authorized_approvers = authorized_approvers or set()
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def check(self, *, action, arguments, context) -> ApprovalVerdict:
        request = ApprovalRequest(
            id=str(uuid.uuid4()),
            action_name=Action(action).value,
            description=f"Approval required for {Action(action).value}",
            payload=dict(arguments),
            requested_by=context.actor_id,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        self.store.create(request)
        self.audit.log(
            "approval_requested",
            request_id=request.id,
            action=request.action_name,
            requested_by=request.requested_by,
            payload=request.payload,
        )

        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            current = self.store.get(request.id)
            if current is None:
                raise RuntimeError("Approval request disappeared.")
            if current.status != ApprovalStatus.PENDING.value:
                break
            time.sleep(self.poll_interval_seconds)
        else:
            current = self.store.get(request.id)
            if current is not None and current.status == ApprovalStatus.PENDING.value:
                current.status = "expired"
                current.reason = "Approval timeout."
                current.decided_at = datetime.now(timezone.utc).isoformat()
                self.store.update(current)
                self.audit.log("approval_expired", request_id=request.id)
            return ApprovalVerdict(ApprovalStatus.DENIED)

        if current.status == ApprovalStatus.APPROVED.value:
            if current.decided_by not in self.authorized_approvers:
                self.audit.log(
                    "approval_rejected_unauthorized",
                    request_id=current.id,
                    decided_by=current.decided_by,
                )
                return ApprovalVerdict(ApprovalStatus.DENIED)
            self.audit.log(
                "action_executed_after_approval",
                request_id=current.id,
                action=current.action_name,
                approved_by=current.decided_by,
            )
            return ApprovalVerdict(ApprovalStatus.APPROVED)

        self.audit.log(
            "action_blocked",
            request_id=current.id,
            action=current.action_name,
            status=current.status,
        )
        return ApprovalVerdict(ApprovalStatus.DENIED)

    def decide(
        self,
        request_id: str,
        *,
        approve: bool,
        decided_by: str,
        reason: str = "",
    ) -> ApprovalRequest:
        request = self.store.get(request_id)
        if request is None:
            raise KeyError(request_id)
        if request.status != ApprovalStatus.PENDING.value:
            raise ValueError("Approval request has already been decided.")
        if decided_by not in self.authorized_approvers:
            request.status = "rejected_unauthorized"
            request.decided_by = decided_by
            request.decided_at = datetime.now(timezone.utc).isoformat()
            request.reason = "Approver is not authorized."
            self.store.update(request)
            self.audit.log(
                "decision_rejected_unauthorized",
                request_id=request_id,
                attempted_by=decided_by,
            )
            raise UnauthorizedApprover(decided_by)

        request.status = (
            ApprovalStatus.APPROVED.value
            if approve
            else ApprovalStatus.DENIED.value
        )
        request.decided_by = decided_by
        request.decided_at = datetime.now(timezone.utc).isoformat()
        request.reason = reason
        self.store.update(request)
        self.audit.log(
            "decision_recorded",
            request_id=request_id,
            status=request.status,
            decided_by=decided_by,
            reason=reason,
        )
        return request