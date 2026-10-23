#!/usr/bin/env python3
"""Print saved agent-loop runs from the evidence folder as readable timelines.

Usage (from the repository root):
    PYTHONPATH=src python3 scripts/show_run_log.py            # list every run
    PYTHONPATH=src python3 scripts/show_run_log.py --last     # newest run
    PYTHONPATH=src python3 scripts/show_run_log.py FILE.jsonl # one run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from observability import format_run, load_index, load_run, resolve_run_log_dir  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", nargs="?", help="a run file to print")
    parser.add_argument("--last", action="store_true", help="print the newest run")
    parser.add_argument(
        "--dir",
        help="run log directory (default: QA_AGENT_TRACE_DIR or evidence/traces/runs)",
    )
    args = parser.parse_args(argv)

    # Reading must never create the folder, so resolve it without RunLogger.
    directory = resolve_run_log_dir(args.dir)
    if args.file:
        path = Path(args.file)
        if not path.exists() and (directory / path).exists():
            path = directory / path  # accept a name exactly as the listing prints it
        if not path.exists():
            print(f"No run file at {args.file}.", file=sys.stderr)
            return 1
        print(format_run(load_run(path)))
        return 0

    runs = load_index(directory)
    if not runs:
        print(f"No finished runs recorded in {directory}.")
        return 0
    if args.last:
        print(format_run(load_run(directory / runs[-1]["file"])))
        return 0

    for row in runs:
        print(
            f"{row['ended_at']}  {row['outcome']:<15}  entries={row['entries']:<3} "
            f"tools={row['tool_calls']:<2} {row['file']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
