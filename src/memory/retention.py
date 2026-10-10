"""Member 5's Week 6 memory retention: the scheduled expiry job and the human clear command.

Retention decision (team vote, Week 6): **memory is kept until a human
clears it** (Option A in the Memory Design and Data Handling Note). The
memory API is therefore built with ``expires_after=MEMORY_EXPIRES_AFTER``,
which is ``None``, so records are written with no expiry time.

This module provides the two ways a record can leave memory:

1. ``purge_expired`` is the **scheduled job**. It deletes only records whose
   ``expires_at`` has passed. It never deletes a record that has no expiry,
   so under Option A it deletes nothing, by design. If the team later sets
   ``MEMORY_EXPIRES_AFTER`` to a period, the same job enforces it without a
   code change. There is deliberately no "backstop" that removes records
   without an expiry: that would silently turn Option A into a fixed period.

2. ``clear_module`` is the **human clear command**. It deletes every record
   for one repository module, and only when a named human (a role or team
   handle, not a personal name) asks for it. It is human-only: nothing in
   ``src/agent/`` or ``src/tools/`` may import this module, and a test
   enforces that, matching the boundary Member 3 put around
   ``record_rejection``.

Both use Member 2's revision-safe ``MemoryStore.delete(expected_revision=...)``.
A record that changed after it was listed (for example a proposal that was
just run) is skipped rather than deleted, so a deletion can never remove
newer information than the run actually looked at.

Every run and every deletion is appended to a JSON Lines audit file. The
audit records identifiers only (namespace, record ID, revision, who, why),
never a test title or any other stored text.

Run from the repository root:

    PYTHONPATH=src python3 -m memory.retention run                 # scheduled job, once
    PYTHONPATH=src python3 -m memory.retention run --dry-run       # show what would go
    PYTHONPATH=src python3 -m memory.retention schedule --every 86400
    PYTHONPATH=src python3 -m memory.retention clear-module src/auth/login.py \\
        --by qa-lead --reason "module rewritten"                    # preview only
    PYTHONPATH=src python3 -m memory.retention clear-module src/auth/login.py \\
        --by qa-lead --reason "module rewritten" --confirm         # deletes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Collection

from .api import MAX_RECORDS_PER_MODULE, namespace_for_module
from .schema import normalize_module
from .store import MemoryStore, StoreConflictError

# ---------------------------------------------------------------------------
# Policy and configuration
# ---------------------------------------------------------------------------

#: Team decision (Week 6, Option A): keep memory until a human clears it.
#: Pass this as ``ProposalMemory(..., expires_after=MEMORY_EXPIRES_AFTER)``.
#: Why: memory exists so the agent never repeats a proposal a developer has
#: already seen or declined. A rejection is final and never rewritten, so any
#: fixed period would delete rejections first and bring declined tests back.
#: Consequences accepted: records accumulate (capped at 1000 per module, a
#: signal for a human to review), and ``rejected_by`` holds a role or team
#: handle rather than a personal name.
MEMORY_EXPIRES_AFTER: timedelta | None = None

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_PATH = REPO_ROOT / "data" / "memory.sqlite3"
DEFAULT_AUDIT_PATH = REPO_ROOT / "data" / "memory_audit.jsonl"
MEMORY_PATH_ENV = "QA_AGENT_MEMORY_PATH"
AUDIT_PATH_ENV = "QA_AGENT_MEMORY_AUDIT_PATH"
APPROVERS_ENV = "QA_AGENT_APPROVERS"

#: How many expired records are fetched per batch, and the most one run may
#: delete. ``MemoryStore.list_expired`` returns at most 1000 rows per call.
BATCH_SIZE = 100
MAX_DELETIONS_PER_RUN = 10_000

#: A clearer must identify themselves with a role or team handle such as
#: ``qa-lead`` or ``team-j``: letters, digits, dot, dash, underscore, up to
#: 64 characters. An email address is refused so personal data is not stored.
_HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def resolve_memory_path() -> Path:
    """Database path: ``QA_AGENT_MEMORY_PATH`` or ``data/memory.sqlite3``."""

    return Path(os.environ.get(MEMORY_PATH_ENV) or DEFAULT_MEMORY_PATH)


def resolve_audit_path() -> Path:
    """Audit path: ``QA_AGENT_MEMORY_AUDIT_PATH`` or ``data/memory_audit.jsonl``."""

    return Path(os.environ.get(AUDIT_PATH_ENV) or DEFAULT_AUDIT_PATH)


def validate_handle(by: str) -> str:
    """Return a clean role/team handle, or raise ``ValueError``."""

    if not isinstance(by, str) or not _HANDLE.match(by.strip()):
        raise ValueError(
            "by must be a role or team handle (letters, digits, '.', '-', '_'; "
            "no spaces or email addresses), for example 'qa-lead'."
        )
    return by.strip()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class RetentionAudit:
    """Append-only JSON Lines record of retention runs and deletions.

    Lines carry identifiers and counts only. Each line is flushed and synced
    before the next deletion, so a crash cannot lose the record of a
    deletion that already happened.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, event: str, **fields: Any) -> None:
        record = {"timestamp": _utc_now().isoformat(), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=True, sort_keys=False)
        with self._lock, open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeletedRecord:
    """Identifiers of one deleted (or, in a dry run, deletable) record."""

    namespace: str
    record_id: str
    revision: int
    expires_at: str | None


@dataclass(frozen=True)
class RetentionReport:
    """What one retention run or clear command did."""

    action: str  # "purge_expired" or "clear_module"
    started_at: str
    dry_run: bool
    examined: int
    deleted: tuple[DeletedRecord, ...] = field(default_factory=tuple)
    skipped_changed: int = 0
    skipped_missing: int = 0
    reached_limit: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "started_at": self.started_at,
            "dry_run": self.dry_run,
            "examined": self.examined,
            "deleted": len(self.deleted),
            "skipped_changed": self.skipped_changed,
            "skipped_missing": self.skipped_missing,
            "reached_limit": self.reached_limit,
        }


# ---------------------------------------------------------------------------
# 1. The scheduled job: delete records whose expiry has passed
# ---------------------------------------------------------------------------


def purge_expired(
    store: MemoryStore,
    *,
    now: datetime,
    audit: RetentionAudit | None = None,
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE,
    max_deletions: int = MAX_DELETIONS_PER_RUN,
) -> RetentionReport:
    """Delete every record whose ``expires_at`` is at or before ``now``.

    Records with no expiry are never touched. Each deletion is revision
    checked: if a record changed after it was listed (its expiry was
    re-stamped by a newer write, or it was already removed), it is skipped.
    ``dry_run`` lists what would be deleted (up to one batch of 1000) and
    deletes nothing.
    """

    _require_aware(now, "now")
    _require_positive(batch_size, "batch_size", maximum=1000)
    _require_positive(max_deletions, "max_deletions")
    started = now.astimezone(timezone.utc).isoformat()

    if dry_run:
        candidates = store.list_expired(before=now, limit=1000)
        report = RetentionReport(
            action="purge_expired",
            started_at=started,
            dry_run=True,
            examined=len(candidates),
            deleted=tuple(_describe(item) for item in candidates),
        )
        _audit_run(audit, report, cutoff=started)
        return report

    deleted: list[DeletedRecord] = []
    examined = skipped_changed = skipped_missing = 0
    attempted: set[tuple[str, str, int]] = set()
    reached_limit = False

    while True:
        batch = [
            item
            for item in store.list_expired(before=now, limit=batch_size)
            if (item.namespace, item.record_id, item.revision) not in attempted
        ]
        if not batch:
            break
        for item in batch:
            if len(deleted) >= max_deletions:
                reached_limit = True
                break
            attempted.add((item.namespace, item.record_id, item.revision))
            examined += 1
            outcome = _delete_one(store, item.namespace, item.record_id, item.revision)
            if outcome == "deleted":
                record = _describe(item)
                deleted.append(record)
                if audit is not None:
                    audit.log(
                        "memory_record_deleted",
                        reason="expired",
                        by="retention-job",
                        namespace=record.namespace,
                        record_id=record.record_id,
                        revision=record.revision,
                        expires_at=record.expires_at,
                    )
            elif outcome == "changed":
                skipped_changed += 1
            else:
                skipped_missing += 1
        if reached_limit:
            break

    report = RetentionReport(
        action="purge_expired",
        started_at=started,
        dry_run=False,
        examined=examined,
        deleted=tuple(deleted),
        skipped_changed=skipped_changed,
        skipped_missing=skipped_missing,
        reached_limit=reached_limit,
    )
    _audit_run(audit, report, cutoff=started)
    return report


def run_scheduled(
    open_store: Callable[[], MemoryStore],
    *,
    interval_seconds: float,
    audit: RetentionAudit | None = None,
    clock: Callable[[], datetime] | None = None,
    stop_event: threading.Event | None = None,
    max_runs: int | None = None,
    on_report: Callable[[RetentionReport], None] | None = None,
) -> int:
    """Run ``purge_expired`` now and then every ``interval_seconds``.

    A fresh store connection is opened for every run and closed afterwards,
    because a SQLite connection must not be shared across threads and a
    long-lived connection would hold the file open between runs. A failed
    run is audited and the schedule continues; the next run retries.
    Returns the number of runs started. Stops when ``stop_event`` is set or
    after ``max_runs`` runs.
    """

    if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (int, float)):
        raise ValueError("interval_seconds must be a number.")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero.")
    if max_runs is not None:
        _require_positive(max_runs, "max_runs")
    clock = clock or _utc_now
    stop_event = stop_event or threading.Event()

    runs = 0
    while not stop_event.is_set():
        runs += 1
        try:
            store = open_store()
            try:
                report = purge_expired(store, now=clock(), audit=audit)
            finally:
                store.close()
            if on_report is not None:
                on_report(report)
        except Exception as error:  # keep the schedule alive; audit the failure
            if audit is not None:
                audit.log("retention_run_failed", error=type(error).__name__)
        if max_runs is not None and runs >= max_runs:
            break
        stop_event.wait(interval_seconds)
    return runs


# ---------------------------------------------------------------------------
# 2. The human clear command: delete one module's memory on request
# ---------------------------------------------------------------------------


def clear_module(
    store: MemoryStore,
    module: str,
    *,
    by: str,
    reason: str,
    now: datetime,
    audit: RetentionAudit,
    authorized: Collection[str] | None = None,
    confirm: bool = False,
) -> RetentionReport:
    """Delete every memory record for ``module``, on a human's request.

    ``by`` must be a role or team handle (see ``validate_handle``) and, when
    ``authorized`` is given, one of those handles. ``reason`` is required and
    is written to the audit log. Without ``confirm=True`` nothing is deleted:
    the report lists what would be removed, so the person can check first.
    """

    handle = validate_handle(by)
    if authorized is not None and handle not in set(authorized):
        audit.log("memory_clear_refused", by=handle, module=_safe_module(module))
        raise PermissionError(f"{handle!r} is not authorized to clear memory.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("A reason is required to clear memory.")
    _require_aware(now, "now")

    canonical = normalize_module(module)
    namespace = namespace_for_module(canonical)
    records = store.list(namespace, limit=MAX_RECORDS_PER_MODULE)
    started = now.astimezone(timezone.utc).isoformat()

    if not confirm:
        report = RetentionReport(
            action="clear_module",
            started_at=started,
            dry_run=True,
            examined=len(records),
            deleted=tuple(_describe(item) for item in records),
        )
        audit.log(
            "memory_clear_previewed",
            by=handle,
            module=canonical,
            records=len(records),
        )
        return report

    deleted: list[DeletedRecord] = []
    skipped_changed = skipped_missing = 0
    for item in records:
        outcome = _delete_one(store, item.namespace, item.record_id, item.revision)
        if outcome == "deleted":
            record = _describe(item)
            deleted.append(record)
            audit.log(
                "memory_record_deleted",
                reason="cleared_by_human",
                by=handle,
                namespace=record.namespace,
                record_id=record.record_id,
                revision=record.revision,
                expires_at=record.expires_at,
            )
        elif outcome == "changed":
            skipped_changed += 1
        else:
            skipped_missing += 1

    report = RetentionReport(
        action="clear_module",
        started_at=started,
        dry_run=False,
        examined=len(records),
        deleted=tuple(deleted),
        skipped_changed=skipped_changed,
        skipped_missing=skipped_missing,
    )
    audit.log(
        "memory_module_cleared",
        by=handle,
        module=canonical,
        reason=reason.strip(),
        **{key: value for key, value in report.summary().items() if key != "action"},
    )
    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delete_one(store: MemoryStore, namespace: str, record_id: str, revision: int) -> str:
    """Revision-checked delete: ``deleted``, ``changed`` or ``missing``."""

    try:
        removed = store.delete(namespace, record_id, expected_revision=revision)
    except StoreConflictError:
        return "changed"
    return "deleted" if removed else "missing"


def _describe(item) -> DeletedRecord:
    return DeletedRecord(
        namespace=item.namespace,
        record_id=item.record_id,
        revision=item.revision,
        expires_at=None if item.expires_at is None else item.expires_at.isoformat(),
    )


def _audit_run(audit: RetentionAudit | None, report: RetentionReport, *, cutoff: str) -> None:
    if audit is not None:
        audit.log("retention_run", cutoff=cutoff, **report.summary())


def _safe_module(module: Any) -> str:
    try:
        return normalize_module(module)
    except ValueError:
        return "<invalid>"


def _require_aware(value: Any, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware datetime.")


def _require_positive(value: Any, label: str, *, maximum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be at most {maximum}.")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _authorized_handles() -> set[str]:
    return {
        value.strip()
        for value in os.environ.get(APPROVERS_ENV, "").split(",")
        if value.strip()
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _print_report(report: RetentionReport) -> None:
    print(json.dumps(report.summary(), indent=2))
    for record in report.deleted:
        verb = "would delete" if report.dry_run else "deleted"
        print(f"  {verb}: {record.namespace} / {record.record_id} (rev {record.revision})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m memory.retention",
        description="Memory retention: scheduled expiry job and human clear command.",
    )
    parser.add_argument("--db", help="memory database (default: QA_AGENT_MEMORY_PATH or data/memory.sqlite3)")
    parser.add_argument("--audit", help="audit file (default: QA_AGENT_MEMORY_AUDIT_PATH or data/memory_audit.jsonl)")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the expiry job once (use this from cron/launchd)")
    run.add_argument("--dry-run", action="store_true", help="list expired records without deleting")

    schedule = commands.add_parser("schedule", help="keep running the expiry job on an interval")
    schedule.add_argument("--every", type=float, default=86_400, help="seconds between runs (default: one day)")

    clear = commands.add_parser("clear-module", help="human command: delete one module's memory")
    clear.add_argument("module", help="repository module path, e.g. src/auth/login.py")
    clear.add_argument("--by", required=True, help="your role or team handle, e.g. qa-lead")
    clear.add_argument("--reason", required=True, help="why the memory is being cleared")
    clear.add_argument("--confirm", action="store_true", help="actually delete (otherwise preview only)")

    args = parser.parse_args(argv)
    db_path = Path(args.db) if args.db else resolve_memory_path()
    audit = RetentionAudit(Path(args.audit) if args.audit else resolve_audit_path())

    if args.command != "schedule" and not db_path.exists():
        # Never create an empty database just to find nothing in it.
        print(f"No memory database at {db_path}; nothing to do.")
        return 0

    try:
        if args.command == "run":
            with MemoryStore(db_path) as store:
                _print_report(purge_expired(store, now=_utc_now(), audit=audit, dry_run=args.dry_run))
            return 0

        if args.command == "schedule":
            print(f"Retention job running every {args.every:g}s against {db_path}. Ctrl+C to stop.")
            try:
                run_scheduled(
                    lambda: MemoryStore(db_path),
                    interval_seconds=args.every,
                    audit=audit,
                    on_report=lambda report: print(json.dumps(report.summary())),
                )
            except KeyboardInterrupt:
                print("Stopped.")
            return 0

        authorized = _authorized_handles()
        if not authorized:
            print(
                f"Set {APPROVERS_ENV} to the role handles allowed to clear memory, "
                'e.g. export QA_AGENT_APPROVERS="qa-lead,team-j".',
                file=sys.stderr,
            )
            return 2
        with MemoryStore(db_path) as store:
            report = clear_module(
                store,
                args.module,
                by=args.by,
                reason=args.reason,
                now=_utc_now(),
                audit=audit,
                authorized=authorized,
                confirm=args.confirm,
            )
        _print_report(report)
        if report.dry_run:
            print("Preview only. Re-run with --confirm to delete these records.")
        return 0
    except PermissionError as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
