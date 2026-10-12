"""Record what the agent did at each step and how long each step took.

This module is the Week 7 Member 2 observability layer. For one agent session
it records a timed, structured ``StepRecord`` for:

- what the model did: model id, prompt version, token usage, provider
  latency, and the action it planned (with the sources it cited);
- what was retrieved: chunk counts, source paths, scores and whether the
  corpus had no evidence;
- which tools were called: tool name, argument key names, dispatch status,
  code and output size;
- how long each step took, including failed steps, which keep the exception
  type name but never its message.

The allocation plan names ``src/logging/observability.py``. A top-level
``logging`` package under ``src/`` would shadow the standard-library
``logging`` module (``pytest.ini`` puts ``src`` on ``sys.path``), so this
follows Member 5's Week 5 choice of ``src/observability/`` for the same
plan entry (``src/logging/tracer.py`` became ``run_logger.py``).

Member 5's ``RunLogger`` remains the fail-closed audit trail of loop
decisions (US-10). This layer adds step-level evidence beside it and must not
change what the agent decides: a sink that cannot be written is counted in
``dropped_writes`` rather than raised, and the instrumentation wrappers added
on top of this module re-raise every exception from the component they wrap.

Records are metadata only. Prompt text, retrieved text, tool argument values,
tool output values and exception messages are never stored, so a record can
be committed as evidence without leaking a query, file content or a token.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TELEMETRY_DIR = REPO_ROOT / "evidence" / "traces" / "observability"
TELEMETRY_DIR_ENV = "QA_AGENT_OBSERVABILITY_DIR"
SCHEMA_VERSION = "qa-agent.step-telemetry/v1"

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


class StepKind(str, Enum):
    """The component a ``StepRecord`` timed."""

    RETRIEVAL = "retrieval"
    SENSE = "sense"
    MODEL_CALL = "model_call"
    PLAN = "plan"
    TOOL_CALL = "tool_call"
    STOP_CHECK = "stop_check"
    LOOP_EVENT = "loop_event"


@dataclass(frozen=True)
class StepRecord:
    """One timed step of a session.

    ``attributes`` is a read-only copy of plain JSON metadata. ``error_type``
    is the exception class name when the step raised, never its message.
    """

    session_id: str
    seq: int
    kind: StepKind
    started_at: datetime
    duration_ms: float
    ok: bool
    error_type: str | None
    attributes: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-ready representation."""

        return {
            "schema": SCHEMA_VERSION,
            "session_id": self.session_id,
            "seq": self.seq,
            "kind": self.kind.value,
            "started_at": self.started_at.isoformat(),
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "error_type": self.error_type,
            "attributes": _thaw(self.attributes),
        }


class StepSink(Protocol):
    """Receives each finished ``StepRecord``."""

    def write(self, record: StepRecord) -> None:
        """Store or forward one record; may raise if it cannot."""


class InMemoryStepSink:
    """Keeps records in a list; useful for tests and scenario runners."""

    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def write(self, record: StepRecord) -> None:
        self.records.append(record)


class JsonlStepSink:
    """Append each record as one JSON line, one file per session.

    Files go under ``evidence/traces/observability/`` unless a directory or
    ``QA_AGENT_OBSERVABILITY_DIR`` is given. They use ``.jsonl`` for the same
    reason as Member 5's run logs: ``scripts/check_sensitive.py`` blocks
    ``*.log`` files from being committed.
    """

    def __init__(self, directory: Path | str | None = None) -> None:
        if directory is None:
            directory = os.environ.get(TELEMETRY_DIR_ENV) or DEFAULT_TELEMETRY_DIR
        self.directory = Path(directory)
        self._paths: dict[str, Path] = {}
        self._lock = threading.Lock()

    def path_for(self, session_id: str) -> Path | None:
        """Return the file a session is being written to, if it has started."""

        return self._paths.get(session_id)

    def write(self, record: StepRecord) -> None:
        line = json.dumps(record.to_dict(), ensure_ascii=True, allow_nan=False)
        with self._lock:
            path = self._paths.get(record.session_id)
            if path is None:
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.directory / _session_filename(record)
                self._paths[record.session_id] = path
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()


def load_steps(path: Path | str) -> list[dict[str, Any]]:
    """Read one telemetry file back as a list of record dictionaries."""

    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class StepScope:
    """Collects attributes for the step currently being timed."""

    def __init__(self) -> None:
        self._attributes: dict[str, Any] = {}
        self.unavailable = False

    def set(self, **attributes: Any) -> None:
        """Add JSON-compatible attributes; non-JSON values are refused."""

        for key, value in attributes.items():
            self._attributes[key] = _freeze(value)

    def capture(self, read: Callable[[], Mapping[str, Any]]) -> None:
        """Add attributes read from a component's result, without raising.

        A result of the wrong shape is the component's failure to report,
        not the telemetry layer's, so the step is marked
        ``attributes_unavailable`` instead of changing the caller's outcome.
        """

        try:
            self.set(**read())
        except Exception:
            self.unavailable = True

    def snapshot(self) -> Mapping[str, Any]:
        attributes = dict(self._attributes)
        if self.unavailable:
            attributes["attributes_unavailable"] = True
        return MappingProxyType(attributes)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ObservabilityRecorder:
    """Time and record the steps of one agent session.

    Create one recorder per session. ``clock`` supplies wall-clock start
    times and ``timer`` supplies monotonic seconds for durations; both are
    injectable so tests are deterministic.
    """

    def __init__(
        self,
        session_id: str,
        *,
        sinks: Iterable[StepSink] = (),
        clock: Callable[[], datetime] = _utc_now,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("Observability recorder requires a session ID.")
        sinks = tuple(sinks)
        for sink in sinks:
            if not callable(getattr(sink, "write", None)):
                raise ValueError("Every telemetry sink must have a write method.")
        if not callable(clock) or not callable(timer):
            raise ValueError("Observability recorder requires a clock and a timer.")
        self.session_id = session_id
        self._sinks = sinks
        self._clock = clock
        self._timer = timer
        self._lock = threading.Lock()
        self._records: list[StepRecord] = []
        self._dropped_writes = 0
        self._first_start: float | None = None
        self._last_end: float | None = None

    @property
    def records(self) -> tuple[StepRecord, ...]:
        """Every record so far, in the order the steps finished."""

        with self._lock:
            return tuple(self._records)

    @property
    def dropped_writes(self) -> int:
        """How many sink writes failed; the records are still kept here."""

        return self._dropped_writes

    @contextmanager
    def step(self, kind: StepKind) -> Iterator[StepScope]:
        """Time the enclosed block as one step and record it.

        An exception from the block is recorded by type name and re-raised
        unchanged.
        """

        kind = StepKind(kind)
        scope = StepScope()
        started_at = self._clock()
        started = self._timer()
        try:
            yield scope
        except Exception as exc:
            self._finish(kind, scope, started_at, started, type(exc).__name__)
            raise
        self._finish(kind, scope, started_at, started, None)

    def _finish(
        self,
        kind: StepKind,
        scope: StepScope,
        started_at: datetime,
        started: float,
        error_type: str | None,
    ) -> None:
        ended = self._timer()
        with self._lock:
            if self._first_start is None:
                self._first_start = started
            self._last_end = ended
            record = StepRecord(
                session_id=self.session_id,
                seq=len(self._records) + 1,
                kind=kind,
                started_at=started_at,
                duration_ms=_milliseconds(ended - started),
                ok=error_type is None,
                error_type=error_type,
                attributes=scope.snapshot(),
            )
            self._records.append(record)
            for sink in self._sinks:
                try:
                    sink.write(record)
                except Exception:
                    # Telemetry must never change what the agent does.
                    self._dropped_writes += 1

    def summary(self) -> dict[str, Any]:
        """Aggregate the session's records into one JSON-ready summary."""

        with self._lock:
            records = list(self._records)
            elapsed = (
                0.0
                if self._first_start is None or self._last_end is None
                else _milliseconds(self._last_end - self._first_start)
            )
        return summarize(
            records,
            session_id=self.session_id,
            elapsed_ms=elapsed,
            dropped_writes=self._dropped_writes,
        )


def summarize(
    records: Iterable[StepRecord],
    *,
    session_id: str,
    elapsed_ms: float | None = None,
    dropped_writes: int = 0,
) -> dict[str, Any]:
    """Summarize step records: per-kind timing, model, retrieval and tool use."""

    records = list(records)
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in StepKind:
        timings = [r.duration_ms for r in records if r.kind is kind]
        if not timings:
            continue
        by_kind[kind.value] = {
            "count": len(timings),
            "errors": sum(1 for r in records if r.kind is kind and not r.ok),
            "total_ms": _round(sum(timings)),
            "mean_ms": _round(sum(timings) / len(timings)),
            "max_ms": _round(max(timings)),
        }

    model_calls = [r for r in records if r.kind is StepKind.MODEL_CALL]
    retrievals = [r for r in records if r.kind is StepKind.RETRIEVAL]
    tool_calls = [r for r in records if r.kind is StepKind.TOOL_CALL]
    plans = [r for r in records if r.kind is StepKind.PLAN and r.ok]
    events = [
        r.attributes.get("event")
        for r in records
        if r.kind is StepKind.LOOP_EVENT and r.ok
    ]

    return {
        "schema": SCHEMA_VERSION,
        "session_id": session_id,
        "steps": len(records),
        "errors": sum(1 for r in records if not r.ok),
        "dropped_writes": dropped_writes,
        "elapsed_ms": elapsed_ms,
        "by_kind": by_kind,
        "model": {
            "calls": len(model_calls),
            "models": _distinct(model_calls, "model"),
            "prompt_versions": _distinct(model_calls, "prompt_version"),
            "input_tokens": _total(model_calls, "input_tokens"),
            "output_tokens": _total(model_calls, "output_tokens"),
            "total_tokens": _total(model_calls, "total_tokens"),
            "provider_latency_ms": _total(model_calls, "provider_latency_ms"),
            "planned_actions": [r.attributes.get("action") for r in plans],
        },
        "retrieval": {
            "calls": len(retrievals),
            "not_in_corpus": sum(
                1 for r in retrievals if r.attributes.get("not_in_corpus") is True
            ),
            "chunks_returned": _total(retrievals, "chunks_returned"),
            "sources": sorted(
                {
                    source
                    for r in retrievals
                    for source in r.attributes.get("source_paths", ())
                }
            ),
        },
        "tools": {
            "calls": len(tool_calls),
            "by_tool": _count(tool_calls, "tool"),
            "by_status": _count(tool_calls, "status"),
        },
        "loop_events": events,
        "outcome": events[-1] if events else None,
    }


def _distinct(records: list[StepRecord], key: str) -> list[str]:
    return sorted(
        {
            value
            for r in records
            if isinstance(value := r.attributes.get(key), str)
        }
    )


def _total(records: list[StepRecord], key: str) -> int | float | None:
    values = [
        value
        for r in records
        if isinstance(value := r.attributes.get(key), (int, float))
        and not isinstance(value, bool)
    ]
    return sum(values) if values else None


def _count(records: list[StepRecord], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        value = r.attributes.get(key)
        label = value if isinstance(value, str) else "unknown"
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def _milliseconds(seconds: float) -> float:
    return _round(max(seconds, 0.0) * 1_000)


def _round(value: float) -> float:
    return round(value, 3)


def _session_filename(record: StepRecord) -> str:
    stamp = record.started_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe = _UNSAFE_FILENAME_CHARS.sub("-", record.session_id).strip("-.")
    return f"{stamp}_{safe[:48] or 'session'}_{uuid.uuid4().hex[:8]}.jsonl"


def _freeze(value: Any) -> Any:
    """Return a read-only copy of plain JSON data, or raise ``TypeError``."""

    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Telemetry attribute keys must be strings.")
            frozen[key] = _freeze(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple, frozenset, set)):
        items = [_freeze(item) for item in value]
        if isinstance(value, (frozenset, set)):
            items.sort(key=repr)
        return tuple(items)
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("Telemetry numbers must be finite.")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("Telemetry attributes must be JSON-compatible.")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
