#!/usr/bin/env python3
"""Human side of the approval gate: tool approvals and test-proposal rejections.

Usage (from the repository root):
    export QA_AGENT_APPROVERS="qa-lead,team-j"     # role or team handles
    PYTHONPATH=src python3 scripts/approve_cli.py list
    PYTHONPATH=src python3 scripts/approve_cli.py approve REQUEST_ID --by qa-lead --reason "..."
    PYTHONPATH=src python3 scripts/approve_cli.py deny REQUEST_ID --by qa-lead --reason "..."

    PYTHONPATH=src python3 scripts/approve_cli.py proposals src/auth/login.py
    PYTHONPATH=src python3 scripts/approve_cli.py reject-proposal src/auth/login.py PROPOSAL_KEY \\
        --by qa-lead --reason "duplicates an existing test"

QA_AGENT_DATA_DIR (default: data) must match the agent process, because both
read and write the same approval_queue.json. QA_AGENT_MEMORY_PATH (default:
data/memory.sqlite3) is the memory database the agent reads.

``reject-proposal`` is the only path that records a human rejecting a test
proposal (Member 3's ``ProposalMemory.record_rejection``). It lives here, in
a human-run script, never in ``src/agent`` or ``src/tools``.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from memory.api import MemoryRecordError, ProposalMemory, UnknownProposalError
from memory.retention import MEMORY_EXPIRES_AFTER, resolve_memory_path, validate_handle
from memory.store import MemoryStore, StoreConflictError
from orchestrator.approval_gate import (
    ApprovalStoreError,
    AuditLogger,
    JSONApprovalGate,
    JSONApprovalStore,
    SelfApprovalError,
    UnauthorizedApprover,
)


def build_gate() -> JSONApprovalGate:
    data_dir = os.environ.get("QA_AGENT_DATA_DIR", "data")
    approvers = {
        value.strip()
        for value in os.environ.get("QA_AGENT_APPROVERS", "").split(",")
        if value.strip()
    }
    if not approvers:
        print(
            "Set QA_AGENT_APPROVERS to the comma-separated role handles "
            'allowed to approve, e.g. export QA_AGENT_APPROVERS="qa-lead,team-j".',
            file=sys.stderr,
        )
        raise SystemExit(2)

    return JSONApprovalGate(
        store=JSONApprovalStore(f"{data_dir}/approval_queue.json"),
        audit=AuditLogger(f"{data_dir}/audit.log"),
        authorized_approvers=approvers,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _age(requested_at: str) -> str:
    try:
        seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(requested_at)).total_seconds()
    except ValueError:
        return "?"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


def reject_proposal(
    memory: ProposalMemory,
    gate: JSONApprovalGate,
    module: str,
    proposal_key: str,
    *,
    by: str,
    reason: str,
):
    """Record that a human rejected a test proposal, and audit it.

    ``by`` must be an authorized role or team handle (not a personal name or
    email address); ``reason`` is required and goes to the audit log only,
    because the memory record has no field for free text.
    """

    handle = validate_handle(by)
    if handle not in gate.authorized_approvers:
        gate.audit.log("proposal_rejection_refused", attempted_by=handle, module=module)
        raise UnauthorizedApprover(handle)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("A reason is required to reject a proposal.")
    record = memory.record_rejection(module, proposal_key, by=handle)
    gate.audit.log(
        "proposal_rejected",
        module=record.module,
        proposal_key=record.proposal_key,
        rejected_by=handle,
        reason=reason.strip(),
    )
    return record


def _open_memory(path: Path) -> tuple[MemoryStore, ProposalMemory]:
    store = MemoryStore(path)
    return store, ProposalMemory(store, expires_after=MEMORY_EXPIRES_AFTER, clock=_utc_now)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("list", help="pending tool-approval requests")

    for command in ("approve", "deny"):
        subcommand = subcommands.add_parser(command, help=f"{command} a tool request")
        subcommand.add_argument("request_id")
        subcommand.add_argument("--by", required=True)
        subcommand.add_argument("--reason", default="")

    proposals = subcommands.add_parser("proposals", help="test proposals remembered for a module")
    proposals.add_argument("module")

    reject = subcommands.add_parser("reject-proposal", help="record a human rejecting a test proposal")
    reject.add_argument("module")
    reject.add_argument("proposal_key")
    reject.add_argument("--by", required=True, help="your role or team handle, e.g. qa-lead")
    reject.add_argument("--reason", required=True)

    args = parser.parse_args(argv)
    gate = build_gate()

    try:
        if args.command == "list":
            pending = gate.store.list_pending()
            if not pending:
                print("No pending approval requests.")
                return
            for request in pending:
                print(
                    f"{request.id} | {request.action_name} | "
                    f"session={request.session_id or '?'} | "
                    f"requested_by={request.requested_by} | "
                    f"age={_age(request.requested_at)} | "
                    f"fingerprint={request.fingerprint[:12] or '?'}\n"
                    f"    {request.payload}"
                )
            return

        if args.command in ("proposals", "reject-proposal"):
            memory_path = resolve_memory_path()
            if not memory_path.exists():
                print(f"No memory database at {memory_path}.", file=sys.stderr)
                raise SystemExit(1)
            store, memory = _open_memory(memory_path)
            try:
                if args.command == "proposals":
                    records = memory.list_for_module(args.module)
                    if not records:
                        print("No remembered proposals for this module.")
                    for record in records:
                        print(f"{record.proposal_key} | {record.status.value} | {record.title}")
                    return
                record = reject_proposal(
                    memory, gate, args.module, args.proposal_key, by=args.by, reason=args.reason
                )
                print(f"{record.proposal_key}: {record.status.value} by {record.rejected_by}")
                return
            finally:
                store.close()

        request = gate.decide(
            args.request_id,
            approve=args.command == "approve",
            decided_by=args.by,
            reason=args.reason,
        )
        print(f"{request.id}: {request.status}")
    except SelfApprovalError as error:
        print(f"Rejected: {error} requested this action and cannot approve it.", file=sys.stderr)
        raise SystemExit(2)
    except UnauthorizedApprover as error:
        print(f"Rejected: {error} is not an authorized approver.", file=sys.stderr)
        raise SystemExit(2)
    except UnknownProposalError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
    except (ApprovalStoreError, MemoryRecordError, StoreConflictError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
    except KeyError as error:
        print(f"Error: no approval request with id {error}.", file=sys.stderr)
        raise SystemExit(1)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
