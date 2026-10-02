"""Save a log of every agent-loop run to the evidence folder.

This module is the Week 5 Member 5 trace sink. Member 2's ``agent.AgentLoop``
emits one ``models.types.TraceEntry`` per lifecycle step and hands it to an
injected ``TraceSink``; it deliberately does not format or persist anything.
``RunLogger`` is that sink:

- every run is written to its own JSON Lines file under
  ``evidence/traces/runs/`` (one ``TraceEntry`` per line, in order);
- every time a run stops (completed, paused, halted or failed) one summary
  row is appended to ``evidence/traces/runs/index.jsonl``;
- each line is flushed and fsynced before ``record`` returns, so a crash
  cannot lose an entry the loop believes was recorded;
- any write failure is raised, never swallowed, so the loop fails closed
  with ``LoopFailure.TRACE_FAILED`` instead of acting without an audit
  trail (US-10);
- strings that look like credentials are replaced with ``[REDACTED]``
  before they reach disk, as a second line of defence behind the loop's
  metadata-only trace payloads.

Files use ``.jsonl`` rather than ``.log`` because ``scripts/check_sensitive.py``
blocks ``*.log`` from being committed, and these files are meant to be
committed as evidence once reviewed.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from models.types import ToolInvocation, TraceEntry

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_LOG_DIR = REPO_ROOT / "evidence" / "traces" / "runs"
RUN_LOG_DIR_ENV = "QA_AGENT_TRACE_DIR"
INDEX_FILE_NAME = "index.jsonl"
SCHEMA_VERSION = "qa-agent.run-log/v1"
REDACTED = "[REDACTED]"

# These mirror agent.LoopEvent's values. They are repeated here rather than
# imported so the logger has no dependency on the loop it observes;
# tests/integration/test_run_logger_agent_loop.py checks they stay in sync.
RUN_OPENING_EVENTS = frozenset({"loop_started", "loop_resumed"})
RUN_TERMINAL_EVENTS = frozenset(
    {"loop_completed", "loop_paused", "loop_halted", "loop_failed"}
)
# A paused run is expected to be resumed into the same file.
RUN_RESUMABLE_EVENTS = frozenset({"loop_paused"})

# A subset of scripts/check_sensitive.py's patterns: anything matching these
# would block the commit, so it is redacted before it is ever written.
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}", re.I),
)

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass
class _OpenRun:
    """Bookkeeping for one run that has not reached a final event yet."""

    run_id: str
    session_id: str
    path: Path
    started_at: str
    entries: int = 0
    tool_calls: int = 0
    ai_decisions: int = 0
    redactions: int = 0


class RunLogger:
    """Trace sink that writes every agent-loop run to ``evidence/traces/runs``.

    Satisfies ``agent.TraceSink``: the only method the loop calls is
    ``record``. A new file is opened for each ``loop_started`` event, and a
    ``loop_resumed`` event continues the paused run's file when this logger
    saw the pause, so one approval hand-off stays in one file.
    """

    def __init__(self, directory: Path | str | None = None) -> None:
        if directory is None:
            directory = os.environ.get(RUN_LOG_DIR_ENV) or DEFAULT_RUN_LOG_DIR
        self.directory = Path(directory)
        self.index_path = self.directory / INDEX_FILE_NAME
        self._lock = threading.Lock()
        self._runs: dict[str, _OpenRun] = {}
        self.directory.mkdir(parents=True, exist_ok=True)

    def record(self, entry: TraceEntry) -> None:
        """Append one trace entry to its run's file; raise if it cannot."""

        if not isinstance(entry, TraceEntry):
            raise TypeError("RunLogger only records TraceEntry objects.")

        with self._lock:
            run = self._run_for(entry)
            payload, redactions = _redact(_entry_to_dict(entry))
            run.entries += 1
            run.redactions += redactions
            if entry.tool_invocation is not None:
                run.tool_calls += 1
            if _enum_value(entry.actor) == "ai":
                run.ai_decisions += 1

            line = {
                "schema": SCHEMA_VERSION,
                "run_id": run.run_id,
                "seq": run.entries,
                **payload,
            }
            if redactions:
                line["redacted"] = True
            _append_line(run.path, line)

            if entry.action in RUN_TERMINAL_EVENTS:
                _append_line(self.index_path, self._summary(run, entry))
                if entry.action not in RUN_RESUMABLE_EVENTS:
                    del self._runs[run.session_id]

    def _run_for(self, entry: TraceEntry) -> _OpenRun:
        current = self._runs.get(entry.session_id)
        if entry.action == "loop_started" or current is None:
            # A fresh start always gets a fresh file. An entry for a session
            # this logger has not seen open is still saved, never dropped.
            current = self._open_run(entry)
            self._runs[entry.session_id] = current
        return current

    def _open_run(self, entry: TraceEntry) -> _OpenRun:
        run_id = uuid.uuid4().hex
        stamp = _filename_timestamp(entry.timestamp)
        safe_session = _UNSAFE_FILENAME_CHARS.sub(
            "-", _redact(entry.session_id)[0]
        ).strip("-.")
        name = f"{stamp}_{safe_session[:48] or 'session'}_{run_id[:8]}.jsonl"
        return _OpenRun(
            run_id=run_id,
            session_id=entry.session_id,
            path=self.directory / name,
            started_at=_isoformat(entry.timestamp),
        )

    def _summary(self, run: _OpenRun, entry: TraceEntry) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "run_id": run.run_id,
            "session_id": _redact(run.session_id)[0],
            "file": run.path.name,
            "started_at": run.started_at,
            "ended_at": _isoformat(entry.timestamp),
            "outcome": entry.action,
            "detail": _redact(entry.detail)[0],
            "entries": run.entries,
            "tool_calls": run.tool_calls,
            "ai_decisions": run.ai_decisions,
            "redactions": run.redactions,
        }


def load_run(path: Path | str) -> list[dict[str, Any]]:
    """Read one run file back as a list of entry dictionaries, in order."""

    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_index(directory: Path | str = DEFAULT_RUN_LOG_DIR) -> list[dict[str, Any]]:
    """Return the latest summary row per run, ordered by when each run last stopped.

    The index is append-only, so a run that paused and was later resumed has
    two rows; only the most recent one describes how it ended.
    """

    path = Path(directory) / INDEX_FILE_NAME
    if not path.exists():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for row in load_run(path):
        latest.pop(row["run_id"], None)
        latest[row["run_id"]] = row
    return list(latest.values())


def format_run(entries: Iterable[Mapping[str, Any]]) -> str:
    """Render a run as a readable timeline for screenshots and reports."""

    lines: list[str] = []
    for entry in entries:
        lines.append(
            f"{entry['seq']:>3}  {entry['timestamp']}  "
            f"{entry['actor']:<13}  {entry['action']:<18}  {entry['detail']}"
        )
        invocation = entry.get("tool_invocation")
        if invocation:
            output = invocation.get("output") or {}
            lines.append(
                f"{'':>5}tool={invocation['tool_name']}  "
                f"kind={output.get('kind')}  code={output.get('code')}  "
                f"output_bytes={output.get('output_bytes')}"
            )
    return "\n".join(lines)


def _entry_to_dict(entry: TraceEntry) -> dict[str, Any]:
    return {
        "session_id": entry.session_id,
        "timestamp": _isoformat(entry.timestamp),
        "actor": _enum_value(entry.actor),
        "action": entry.action,
        "detail": entry.detail,
        "tool_invocation": _invocation_to_dict(entry.tool_invocation),
    }


def _invocation_to_dict(invocation: ToolInvocation | None) -> dict[str, Any] | None:
    if invocation is None:
        return None
    return {
        "tool_name": invocation.tool_name,
        "input": _plain_json(invocation.input),
        "output": _plain_json(invocation.output),
        "called_at": _isoformat(invocation.called_at),
    }


def _plain_json(value: Any) -> Any:
    """Copy mappings/sequences to plain dicts/lists; stringify anything else."""

    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return _isoformat(value)
    return _enum_value(value) if hasattr(value, "value") else str(value)


def _redact(value: Any) -> tuple[Any, int]:
    """Return ``value`` with credential-like substrings replaced, and a count."""

    if isinstance(value, str):
        count = 0
        for pattern in _SECRET_PATTERNS:
            value, hits = pattern.subn(REDACTED, value)
            count += hits
        return value, count
    if isinstance(value, dict):
        total = 0
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            safe_key, key_hits = _redact(key)
            cleaned[safe_key], item_hits = _redact(item)
            total += key_hits + item_hits
        return cleaned, total
    if isinstance(value, list):
        total = 0
        cleaned_list = []
        for item in value:
            safe_item, hits = _redact(item)
            cleaned_list.append(safe_item)
            total += hits
        return cleaned_list, total
    return value, 0


def _append_line(path: Path, record: Mapping[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=True, allow_nan=False, sort_keys=False)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _isoformat(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _filename_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%dT%H%M%S%fZ")
    return "unknown-time"
