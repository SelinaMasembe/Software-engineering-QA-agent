#!/usr/bin/env python3
"""Run the ten Week 2 prompt cases against a real model, single-shot.

Week 8, Member 3. For each case, prompt version and run, this script builds
the evidence block with ``rag.context_builder.build_context`` (the same
wrapper the agent loop shows the model), loads the prompt text with
``prompts.loader.load_prompt``, makes ONE model call, parses the reply with
``ProposalSet.model_validate_json``, checks citations with
``orchestrator.validation.validate_citations``, and scores the result with
``evaluation.scorer.score_case``.

Single-shot means no agent loop runs. ``tool_selection`` and
``stop_reason`` need the loop, so they are recorded as "not applicable to
single-shot" and never shown as passed.

Without ``--live`` a stub client returns a canned, valid reply and no
model client is constructed, so no key is read and no network call is made.
With ``--live`` the client comes from ``config.build_model_client``, which
reads MODEL_ENDPOINT, MODEL_API_KEY and MODEL_NAME from the environment.
This script never reads a .env file, never prints the key, and never writes
it or any request header to an output file.

Each invocation writes to its own new folder under ``--out``:
one JSON file per call, ``summary.csv`` (one row per call) and
``summary.json`` (counts per prompt version, never averaged).

Usage (Git Bash, from the repository root):
    python scripts/real_model_eval.py --prompt-version v1.3 --runs 1
    python scripts/real_model_eval.py --prompt-version v1.3 --runs 1 --live
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evaluation.scorer import Expectation, ScenarioObservation, score_case  # noqa: E402
from models.client import (  # noqa: E402
    ModelCallResult,
    ModelIntegrationError,
    ModelRateLimitError,
    TokenUsage,
)
from models.types import Action, ProposalSet, UntraceableProposalError  # noqa: E402
from orchestrator.validation import validate_citations  # noqa: E402
from prompts.loader import load_prompt  # noqa: E402
from rag.chunking import Chunk, DocumentType  # noqa: E402
from rag.context_builder import AssembledContext, build_context  # noqa: E402
from rag.retrieval import IndexManifest, RetrievalResult  # noqa: E402
from rag.retriever import RetrievedChunk  # noqa: E402

CASES_PATH = REPO_ROOT / "tests" / "fixtures" / "prompt_eval_cases.json"
DEFAULT_OUT = REPO_ROOT / "evidence" / "test-runs" / "week8" / "real-model"
PROMPT_ID = "propose_action"
SUPPORTED_VERSIONS = ("v1.1", "v1.3")

# HTTP 429: wait, then retry at most twice. Every retry is recorded.
RATE_LIMIT_BACKOFF_SECONDS = (20.0, 60.0)
MAX_CONSECUTIVE_FAILURES = 3

NOT_APPLICABLE = "not applicable to single-shot"
SINGLE_SHOT_NOT_APPLICABLE = ("tool_selection", "stop_reason")
SCORED_CHECKS = ("task_completion", "groundedness", "instruction_following", "safety_violation")

# The Week 2 cases give a requirement ID and text but no file path. The
# evidence wrapper needs a path for every chunk, so one is built here.
REQUIREMENT_PATH_TEMPLATE = "requirements/{requirement_id}.md"

STUB_MODEL = "stub-no-network"


# ---------------------------------------------------------------------------
# Cases and context.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptCase:
    """One Week 2 case, as read from tests/fixtures/prompt_eval_cases.json."""

    case_id: str
    category: str
    requirement_id: str
    requirement_text: str
    source_path: str
    source_text: str
    expected_actions: tuple[str, ...]
    expected_confidence: tuple[str, ...]
    forbidden_text_substrings: tuple[str, ...]
    disallowed_source_paths: tuple[str, ...]

    @property
    def requirement_path(self) -> str:
        return REQUIREMENT_PATH_TEMPLATE.format(requirement_id=self.requirement_id)


def load_cases(path: Path = CASES_PATH) -> list[PromptCase]:
    """Read the ten cases. The file is only read, never changed."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        PromptCase(
            case_id=entry["id"],
            category=entry["category"],
            requirement_id=entry["requirement_id"],
            requirement_text=entry["requirement_text"],
            source_path=entry["source_path"].replace("\\", "/"),
            source_text=entry["source_text"],
            expected_actions=tuple(entry["expected_actions"]),
            expected_confidence=tuple(entry.get("expected_confidence") or ()),
            forbidden_text_substrings=tuple(entry.get("forbidden_text_substrings", ())),
            disallowed_source_paths=tuple(entry.get("disallowed_source_paths", ())),
        )
        for entry in raw
    ]
    if len(cases) != 10:
        raise ValueError(f"Expected exactly 10 Week 2 cases, found {len(cases)}.")
    return cases


def _line_count(text: str) -> int:
    return max(1, len(text.splitlines()))


def build_case_context(case: PromptCase) -> AssembledContext:
    """Two chunks (requirement, then source) through the real evidence wrapper."""

    requirement = Chunk(
        f"{case.requirement_path}#L1-L{_line_count(case.requirement_text)}",
        case.requirement_text,
        case.requirement_path,
        DocumentType.REQUIREMENT,
        1,
        _line_count(case.requirement_text),
        case.requirement_id,
    )
    source = Chunk(
        f"{case.source_path}#L1-L{_line_count(case.source_text)}",
        case.source_text,
        case.source_path,
        DocumentType.CODE,
        1,
        _line_count(case.source_text),
    )
    retrieved = tuple(RetrievedChunk(c, 1.0, 1.0, ()) for c in (requirement, source))
    result = RetrievalResult(
        query=case.requirement_text,
        chunks=retrieved,
        not_in_corpus=False,
        manifest=IndexManifest("week2-prompt-cases", "constructed", 2, 2),
        candidates_considered=2,
        top_score=1.0,
        top_term_coverage=1.0,
        latency_ms=0,
    )
    return build_context(result)


# ---------------------------------------------------------------------------
# Clients.
# ---------------------------------------------------------------------------


class StubClient:
    """Dry-run client: a canned, schema-valid reply that cites the source path.

    Never touches the network and never reads a key. Its replies are not
    model output and are labelled with ``model = "stub-no-network"``.
    """

    model = STUB_MODEL
    temperature = None
    max_tokens = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.next_source_path = ""

    def generate(self, *, system_prompt: str, user_content: str) -> ModelCallResult:
        self.calls.append((system_prompt, user_content))
        reply = {
            "action": "propose_test",
            "arguments": {"title": "stub proposal", "target": self.next_source_path},
            "rationale": "Stub reply for a dry run. Not model output.",
            "evidence": [{"source_path": self.next_source_path, "note": "stub"}],
            "confidence": "high",
        }
        return ModelCallResult(
            raw_text=json.dumps(reply),
            model=STUB_MODEL,
            latency_ms=0,
            usage=TokenUsage(0, 0, 0),
        )


def build_live_client() -> Any:
    """The real client, from validated environment settings. Imported lazily."""

    from config import build_model_client

    return build_model_client()


# ---------------------------------------------------------------------------
# One call.
# ---------------------------------------------------------------------------


@dataclass
class CallRecord:
    case_id: str
    category: str
    prompt_version: str
    run_index: int
    timestamp_utc: str
    model_requested: str
    temperature: float | None
    max_tokens: int | None
    live: bool
    status: str = "pending"  # ok | call_failed | parse_failed
    attempts: int = 0
    retries_after_429: int = 0
    model_returned: str | None = None
    latency_ms: int | None = None
    usage: dict[str, int | None] = field(default_factory=dict)
    prompt_sha256: str = ""
    user_content: str = ""
    allowed_source_paths: list[str] = field(default_factory=list)
    context_flags: list[str] = field(default_factory=list)
    raw_model_text: str | None = None
    parse_result: str | None = None
    action: str | None = None
    confidence: str | None = None
    evidence_paths: list[str] = field(default_factory=list)
    citations_valid: bool | None = None
    citation_error: str | None = None
    cites_requirement_id_as_path: bool | None = None
    criteria: dict[str, dict[str, Any]] = field(default_factory=dict)
    outcome: str | None = None  # PASS | FAIL | NOT_SCORED
    exception: str | None = None


def _expectation(case: PromptCase) -> Expectation:
    # Same mapping as tests/test_evaluation_scorer.py's Week 2 parity test.
    return Expectation(
        final_actions=case.expected_actions,
        confidence=case.expected_confidence,
        forbidden_in_output=case.forbidden_text_substrings,
    )


@dataclass(frozen=True)
class _ScoredPromptCase:
    case_id: str
    category: str
    expected: Expectation
    risk_id: str = ""
    known_gap: str | None = None
    gap_check: str | None = None


def _call_with_backoff(
    client: Any,
    system_prompt: str,
    user_content: str,
    record: CallRecord,
    budget: "CallBudget",
    sleep: Callable[[float], None],
) -> ModelCallResult:
    """One logical call. A 429 waits and retries at most twice, each recorded."""

    while True:
        budget.take()
        record.attempts += 1
        try:
            return client.generate(system_prompt=system_prompt, user_content=user_content)
        except ModelRateLimitError:
            if record.retries_after_429 >= len(RATE_LIMIT_BACKOFF_SECONDS) or budget.exhausted():
                raise
            wait = RATE_LIMIT_BACKOFF_SECONDS[record.retries_after_429]
            record.retries_after_429 += 1
            print(
                f"  HTTP 429 on {record.case_id} {record.prompt_version} run "
                f"{record.run_index}: waiting {wait:g}s, retry {record.retries_after_429} of "
                f"{len(RATE_LIMIT_BACKOFF_SECONDS)}"
            )
            sleep(wait)


def _score(case: PromptCase, proposal: ProposalSet, context: AssembledContext) -> tuple[str, dict]:
    observation = ScenarioObservation(
        proposal=proposal,
        allowed_source_paths=context.allowed_source_paths,
        not_in_corpus=context.not_in_corpus,
        model_inputs=(context.text,),
        context_flags=context.flagged,
    )
    score = score_case(_ScoredPromptCase(case.case_id, case.category, _expectation(case)), observation)
    criteria: dict[str, dict[str, Any]] = {}
    for check in score.checks:
        if check.name in SINGLE_SHOT_NOT_APPLICABLE:
            criteria[check.name] = {"result": NOT_APPLICABLE}
        elif check.name == "latency":
            criteria[check.name] = {"result": "reported only", "detail": check.detail}
        else:
            criteria[check.name] = {"result": "pass" if check.passed else "fail", "detail": check.detail}
    # Outcome uses only the criteria that apply to one call.
    failed = [name for name in SCORED_CHECKS if criteria[name]["result"] == "fail"]
    return ("FAIL" if failed else "PASS"), criteria


def run_one(
    case: PromptCase,
    version: str,
    prompt_text: str,
    run_index: int,
    client: Any,
    budget: "CallBudget",
    *,
    live: bool,
    sleep: Callable[[float], None] = time.sleep,
) -> CallRecord:
    context = build_case_context(case)
    record = CallRecord(
        case_id=case.case_id,
        category=case.category,
        prompt_version=version,
        run_index=run_index,
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        model_requested=getattr(client, "model", None) or "",
        temperature=getattr(client, "temperature", None),
        max_tokens=getattr(client, "max_tokens", None),
        live=live,
        prompt_sha256=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        user_content=context.text,
        allowed_source_paths=sorted(context.allowed_source_paths),
        context_flags=sorted({f.rule_id for cf in context.flagged for f in cf.flags}),
    )
    if isinstance(client, StubClient):
        client.next_source_path = case.source_path

    try:
        result = _call_with_backoff(client, prompt_text, context.text, record, budget, sleep)
    except BudgetExhausted:
        raise
    except ModelIntegrationError as exc:
        record.status = "call_failed"
        record.exception = f"{type(exc).__name__}: {exc}"
        record.outcome = "NOT_SCORED"
        return record

    record.model_returned = result.model
    record.latency_ms = result.latency_ms
    record.usage = {
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "total_tokens": result.usage.total_tokens,
    }
    record.raw_model_text = result.raw_text

    try:
        proposal = ProposalSet.model_validate_json(result.raw_text)
    except ModelIntegrationError as exc:
        record.status = "parse_failed"
        record.parse_result = f"invalid: {exc}"
        record.exception = f"{type(exc).__name__}: {exc}"
        record.outcome = "NOT_SCORED"
        return record

    record.status = "ok"
    record.parse_result = "valid"
    record.action = proposal.action.value
    record.confidence = proposal.confidence.value
    record.evidence_paths = [ref.source_path for ref in proposal.evidence]
    record.cites_requirement_id_as_path = case.requirement_id in record.evidence_paths
    try:
        validate_citations(proposal, context.allowed_source_paths)
        record.citations_valid = True
    except UntraceableProposalError as exc:
        record.citations_valid = False
        record.citation_error = str(exc)
    record.outcome, record.criteria = _score(case, proposal, context)
    return record


# ---------------------------------------------------------------------------
# The run.
# ---------------------------------------------------------------------------


class BudgetExhausted(Exception):
    """--max-calls reached. The run stops; nothing further is sent."""


class CallBudget:
    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.used = 0

    def exhausted(self) -> bool:
        return self.used >= self.max_calls

    def take(self) -> None:
        if self.exhausted():
            raise BudgetExhausted(f"--max-calls {self.max_calls} reached")
        self.used += 1


def _redact(text: str, secret: str | None) -> str:
    # Belt and braces: nothing written should ever contain the key, but if a
    # provider echoed it back it is removed before the file is written.
    if secret and secret in text:
        return text.replace(secret, "[REDACTED]")
    return text


def _write_json(path: Path, payload: Any, secret: str | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=False)
    path.write_text(_redact(text, secret) + "\n", encoding="utf-8", newline="\n")


CSV_FIELDS = (
    "case_id", "category", "prompt_version", "run_index", "live", "model_requested",
    "model_returned", "temperature", "max_tokens", "status", "attempts", "retries_after_429",
    "latency_ms", "input_tokens", "output_tokens", "total_tokens", "action", "confidence",
    "evidence_count", "citations_valid", "cites_requirement_id_as_path", "outcome",
    "failed_criteria", "exception",
)


def _csv_row(r: CallRecord) -> dict[str, Any]:
    failed = [name for name, c in r.criteria.items() if c.get("result") == "fail"]
    return {
        "case_id": r.case_id, "category": r.category, "prompt_version": r.prompt_version,
        "run_index": r.run_index, "live": r.live, "model_requested": r.model_requested,
        "model_returned": r.model_returned, "temperature": r.temperature,
        "max_tokens": r.max_tokens, "status": r.status, "attempts": r.attempts,
        "retries_after_429": r.retries_after_429, "latency_ms": r.latency_ms,
        "input_tokens": r.usage.get("input_tokens"), "output_tokens": r.usage.get("output_tokens"),
        "total_tokens": r.usage.get("total_tokens"), "action": r.action,
        "confidence": r.confidence, "evidence_count": len(r.evidence_paths),
        "citations_valid": r.citations_valid,
        "cites_requirement_id_as_path": r.cites_requirement_id_as_path,
        "outcome": r.outcome, "failed_criteria": ";".join(failed), "exception": r.exception,
    }


def summarize_records(records: list[CallRecord], versions: list[str]) -> dict[str, Any]:
    """Counts per prompt version. Failures are counted, never averaged away."""

    per_version: dict[str, Any] = {}
    for version in versions:
        rows = [r for r in records if r.prompt_version == version]
        failures: dict[str, int] = {}
        for r in rows:
            if r.status != "ok":
                key = r.status if r.exception is None else f"{r.status}: {r.exception.split(':')[0]}"
                failures[key] = failures.get(key, 0) + 1
        criteria: dict[str, dict[str, int]] = {}
        for name in SCORED_CHECKS:
            criteria[name] = {
                "pass": sum(1 for r in rows if r.criteria.get(name, {}).get("result") == "pass"),
                "fail": sum(1 for r in rows if r.criteria.get(name, {}).get("result") == "fail"),
            }
        per_version[version] = {
            "calls_recorded": len(rows),
            "valid_parse": sum(1 for r in rows if r.parse_result == "valid"),
            "valid_citations": sum(1 for r in rows if r.citations_valid is True),
            "invalid_citations": sum(1 for r in rows if r.citations_valid is False),
            "cites_requirement_id_as_path": sum(1 for r in rows if r.cites_requirement_id_as_path),
            "no_action_returned": sum(1 for r in rows if r.action == Action.NO_ACTION.value),
            "no_action_with_empty_evidence": sum(
                1 for r in rows if r.action == Action.NO_ACTION.value and not r.evidence_paths
            ),
            "outcomes": {
                key: sum(1 for r in rows if r.outcome == key) for key in ("PASS", "FAIL", "NOT_SCORED")
            },
            "failures": failures,
            "retries_after_429": sum(r.retries_after_429 for r in rows),
            "criteria": criteria,
            "not_applicable_to_single_shot": list(SINGLE_SHOT_NOT_APPLICABLE),
        }
    return per_version


@dataclass
class RunResult:
    out_dir: Path
    records: list[CallRecord]
    stopped_early: str | None
    calls_made: int


def run_evaluation(
    *,
    versions: list[str],
    runs: int,
    live: bool,
    out_root: Path,
    max_calls: int,
    client_factory: Callable[[], Any] = build_live_client,
    sleep: Callable[[float], None] = time.sleep,
    cases: list[PromptCase] | None = None,
    stamp: str | None = None,
) -> RunResult:
    cases = load_cases() if cases is None else cases
    prompts = {v: load_prompt(PROMPT_ID, v).text for v in versions}
    client = client_factory() if live else StubClient()
    secret = getattr(client, "api_key", None) if live else None

    planned = len(cases) * len(versions) * runs
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out_root / f"{stamp}_{'live' if live else 'dryrun'}"
    out_dir.mkdir(parents=True, exist_ok=False)
    calls_dir = out_dir / "calls"
    calls_dir.mkdir()

    print("PLAN")
    print(f"  live: {'ON (real model calls)' if live else 'off (stub client, no network)'}")
    print(f"  model: {getattr(client, 'model', '?')}")
    print(f"  temperature: {getattr(client, 'temperature', None)}  max_tokens: {getattr(client, 'max_tokens', None)}")
    print(f"  prompt versions: {', '.join(versions)}  runs: {runs}  cases: {len(cases)}")
    print(f"  planned calls: {planned}  hard stop (--max-calls): {max_calls}"
          + ("  (the run will stop before finishing)" if planned > max_calls else ""))
    print(f"  output: {out_dir}")

    budget = CallBudget(max_calls)
    records: list[CallRecord] = []
    stopped: str | None = None
    consecutive = 0
    try:
        for version in versions:
            for run_index in range(1, runs + 1):
                for case in cases:
                    record = run_one(
                        case, version, prompts[version], run_index, client, budget,
                        live=live, sleep=sleep,
                    )
                    records.append(record)
                    name = f"{case.case_id}__{version}__run{run_index}.json"
                    _write_json(calls_dir / name, record.__dict__, secret)
                    print(f"  {case.case_id} {version} run {run_index}: {record.status}, "
                          f"action={record.action}, citations_valid={record.citations_valid}, "
                          f"outcome={record.outcome}")
                    consecutive = consecutive + 1 if record.status != "ok" else 0
                    if consecutive >= MAX_CONSECUTIVE_FAILURES:
                        raise _Stop(
                            f"{MAX_CONSECUTIVE_FAILURES} consecutive failures; last: {record.exception}"
                        )
    except BudgetExhausted as exc:
        stopped = str(exc)
    except _Stop as exc:
        stopped = str(exc)

    with (out_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for r in records:
            writer.writerow({k: _redact("" if v is None else str(v), secret) for k, v in _csv_row(r).items()})

    summary = {
        "live": live,
        "model": getattr(client, "model", None),
        "prompt_versions": versions,
        "runs": runs,
        "planned_calls": planned,
        "http_attempts": budget.used,
        "max_calls": max_calls,
        "stopped_early": stopped,
        "requirement_path_template": REQUIREMENT_PATH_TEMPLATE,
        "note": (
            "Single-shot calls through build_context, not the agent loop. "
            "tool_selection and stop_reason are not applicable. Groundedness is "
            "citation validity only. Synthetic Week 2 inputs."
        ),
        "per_version": summarize_records(records, versions),
    }
    _write_json(out_dir / "summary.json", summary, secret)

    print("SUMMARY")
    print(json.dumps(summary["per_version"], indent=2))
    if stopped:
        print(f"STOPPED EARLY: {stopped}")
    return RunResult(out_dir, records, stopped, budget.used)


class _Stop(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Single-shot real-model run of the ten Week 2 cases.")
    parser.add_argument("--prompt-version", action="append", choices=SUPPORTED_VERSIONS,
                        dest="versions", help="v1.1 or v1.3; repeat for both (default v1.3).")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--live", action="store_true",
                        help="Call the real model. Without it a stub is used and nothing is sent.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-calls", type=int, default=80,
                        help="Hard stop on HTTP attempts, retries included.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.runs < 1 or args.max_calls < 1:
        raise SystemExit("--runs and --max-calls must be at least 1.")
    versions = list(dict.fromkeys(args.versions or ["v1.3"]))
    try:
        result = run_evaluation(
            versions=versions, runs=args.runs, live=args.live,
            out_root=args.out, max_calls=args.max_calls,
        )
    except ModelIntegrationError as exc:
        # Configuration errors name the variable, never its value.
        print(f"Could not start: {exc}", file=sys.stderr)
        return 2
    return 1 if result.stopped_early else 0


if __name__ == "__main__":
    raise SystemExit(main())
