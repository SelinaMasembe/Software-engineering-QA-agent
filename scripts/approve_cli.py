#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys

from orchestration.approval_gate import (
    AuditLogger,
    JSONApprovalGate,
    JSONApprovalStore,
    UnauthorizedApprover,
)


def build_gate() -> JSONApprovalGate:
    data_dir = os.environ.get("QA_AGENT_DATA_DIR", "data")
    approvers = {
        value.strip()
        for value in os.environ.get(
            "QA_AGENT_APPROVERS", "Alice,Bob"
        ).split(",")
        if value.strip()
    }

    return JSONApprovalGate(
        store=JSONApprovalStore(f"{data_dir}/approval_queue.json"),
        audit=AuditLogger(f"{data_dir}/audit.log"),
        authorized_approvers=approvers,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("list")

    for command in ("approve", "deny"):
        subcommand = subcommands.add_parser(command)
        subcommand.add_argument("request_id")
        subcommand.add_argument("--by", required=True)
        subcommand.add_argument("--reason", default="")

    args = parser.parse_args()
    gate = build_gate()

    if args.command == "list":
        pending = gate.store.list_pending()
        if not pending:
            print("No pending approval requests.")
            return

        for request in pending:
            print(
                f"{request.id} | {request.action_name} | "
                f"{request.requested_by} | {request.payload}"
            )
        return

    try:
        request = gate.decide(
            args.request_id,
            approve=args.command == "approve",
            decided_by=args.by,
            reason=args.reason,
        )
        print(f"{request.id}: {request.status}")
    except UnauthorizedApprover as error:
        print(f"Rejected: {error}", file=sys.stderr)
        raise SystemExit(2)
    except (KeyError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()