#!/usr/bin/env python3
"""Human side of the approval gate: list, approve or deny pending requests.

Usage (from the repository root):
    export QA_AGENT_APPROVERS="Alice,Bob"
    PYTHONPATH=src python3 scripts/approve_cli.py list
    PYTHONPATH=src python3 scripts/approve_cli.py approve REQUEST_ID --by Alice --reason "..."
    PYTHONPATH=src python3 scripts/approve_cli.py deny REQUEST_ID --by Alice --reason "..."

QA_AGENT_DATA_DIR (default: data) must match the agent process, because both
read and write the same approval_queue.json.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

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
            "Set QA_AGENT_APPROVERS to the comma-separated names of the people "
            'allowed to approve, e.g. export QA_AGENT_APPROVERS="Alice,Bob".',
            file=sys.stderr,
        )
        raise SystemExit(2)

    return JSONApprovalGate(
        store=JSONApprovalStore(f"{data_dir}/approval_queue.json"),
        audit=AuditLogger(f"{data_dir}/audit.log"),
        authorized_approvers=approvers,
    )


def _age(requested_at: str) -> str:
    try:
        seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(requested_at)).total_seconds()
    except ValueError:
        return "?"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("list")

    for command in ("approve", "deny"):
        subcommand = subcommands.add_parser(command)
        subcommand.add_argument("request_id")
        subcommand.add_argument("--by", required=True)
        subcommand.add_argument("--reason", default="")

    args = parser.parse_args()
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
    except ApprovalStoreError as error:
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
