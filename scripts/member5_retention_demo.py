#!/usr/bin/env python3
"""Demonstrate Member 5's Week 6 memory retention and human memory controls.

Everything runs against a temporary database that is deleted afterwards.

1. Option A (the team decision): records have no expiry, so the scheduled
   job deletes nothing, even "ten years" later.
2. If a period were ever configured, the same job deletes only the records
   whose expiry has passed.
3. A human records a rejection of a test proposal (the approval path).
4. A human clears one module's memory: preview first, then --confirm.

Run from the repository root:
    PYTHONPATH=src python3 scripts/member5_retention_demo.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from memory.api import ProposalMemory, namespace_for_module  # noqa: E402
from memory.retention import (  # noqa: E402
    MEMORY_EXPIRES_AFTER,
    RetentionAudit,
    clear_module,
    purge_expired,
)
from memory.store import MemoryStore  # noqa: E402
from models.types import Confidence, EvidenceRef, TestProposal  # noqa: E402

START = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
LOGIN = "src/auth/login.py"
BILLING = "src/billing/discounts.py"


def proposal(title: str) -> TestProposal:
    return TestProposal(
        title=title,
        target=None,
        rationale="Demo proposal.",
        evidence=(EvidenceRef(source_path="requirements/authentication.md"),),
        confidence=Confidence.HIGH,
        requirement_id="REQ-AUTH-01",
    )


def count(store: MemoryStore, module: str) -> int:
    return len(store.list(namespace_for_module(module), limit=1000))


def main() -> None:
    directory = Path(tempfile.mkdtemp(prefix="member5_retention_demo_"))
    try:
        store = MemoryStore(directory / "memory.sqlite3")
        audit = RetentionAudit(directory / "memory_audit.jsonl")
        now = [START]
        option_a = ProposalMemory(store, expires_after=MEMORY_EXPIRES_AFTER, clock=lambda: now[0])

        print("=== 1. Option A: keep until a human clears it")
        first = option_a.record_proposal(LOGIN, proposal("Lock account after five failures"))
        option_a.record_proposal(LOGIN, proposal("Reset counter after a success"))
        report = purge_expired(store, now=START + timedelta(days=3650), audit=audit)
        print(f"   job ran 10 years later: deleted={len(report.deleted)}, "
              f"{LOGIN} still holds {count(store, LOGIN)} records")

        print("\n=== 2. If a 30-day period were configured instead")
        with_period = ProposalMemory(store, expires_after=timedelta(days=30), clock=lambda: now[0])
        with_period.record_proposal(BILLING, proposal("Discount applied once"))
        report = purge_expired(store, now=START + timedelta(days=31), audit=audit)
        print(f"   job ran on day 31: deleted={len(report.deleted)} (the expired {BILLING} record); "
              f"{LOGIN} untouched: {count(store, LOGIN)} records")

        print("\n=== 3. A human rejects a proposal (approval path, role handle)")
        rejected = option_a.record_rejection(LOGIN, first.proposal_key, by="qa-lead")
        print(f"   {rejected.proposal_key}: {rejected.status.value} by {rejected.rejected_by}")

        print("\n=== 4. A human clears one module's memory")
        preview = clear_module(store, LOGIN, by="qa-lead", reason="module rewritten",
                               now=START, audit=audit, authorized={"qa-lead"})
        print(f"   preview: would delete {len(preview.deleted)}; still holds {count(store, LOGIN)}")
        done = clear_module(store, LOGIN, by="qa-lead", reason="module rewritten",
                            now=START, audit=audit, authorized={"qa-lead"}, confirm=True)
        print(f"   confirmed: deleted {len(done.deleted)}; now holds {count(store, LOGIN)}")

        print("\n=== audit log (identifiers only, no test titles)")
        for line in audit.path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            event.pop("timestamp")
            print("  ", json.dumps(event))
        store.close()
    finally:
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    main()
