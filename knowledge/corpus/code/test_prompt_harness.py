"""Week 2 prompt-evaluation harness (Member 4, Quality/Security Lead).

Runs the ten evaluation cases in tests/fixtures/prompt_eval_cases.json
against the "propose_action" prompt (docs/prompts/propose_action/) through
Member 2's generate_test_proposals() pipeline, and records what the model
actually returned versus what was expected.

Two modes:

  offline (default) - scores each case against a hand-written, schema-valid
      "simulated_model_response" bundled in the fixture, using a fake
      ModelClient. No network access or API key is required, so this mode is
      safe to run in CI and under `unittest discover`. Two of the ten cases
      are deliberate red-team probes with an intentionally NON-compliant
      simulated response; those two are EXPECTED to fail, as proof the
      harness itself catches prompt-injection compliance and fabricated
      citations rather than rubber-stamping everything.

  real - calls a live, configured chat-completions model and produces the
      genuine Week 2 expected-vs-actual evaluation evidence. Requires
      --endpoint, --model, and an API key in the environment variable named
      by --api-key-env (default MODEL_API_KEY). Mirrors the security practice
      already used in scripts/member2_model_smoke.py: the key is read from
      the environment, never taken as a command-line argument.

Usage:
    PYTHONPATH=src python3 tests/test_prompt_harness.py
    PYTHONPATH=src python3 tests/test_prompt_harness.py --mode real \\
        --endpoint "https://provider.example/v1/chat/completions" \\
        --model "chosen-model-id"

Also runnable as part of the automated suite:
    PYTHONPATH=src python3 -m unittest tests.test_prompt_harness -v
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models.client import (  # noqa: E402
    ChatCompletionsClient,
    ModelCallResult,
    ModelResponseError,
    TokenUsage,
)
from prompts.loader import load_latest, load_prompt  # noqa: E402
from rag.pipeline import (  # noqa: E402
    PipelineResult,
    ProposalInput,
    generate_test_proposals,
    parse_json_object,
)

CASES_PATH = TESTS_DIR / "fixtures" / "prompt_eval_cases.json"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "evaluation" / "week2-ten-case-evaluation.md"

ALLOWED_ACTIONS = {
    "search_repo",
    "read_file",
    "run_tests",
    "draft_issue",
    "propose_test",
    "no_action",
}
ALLOWED_CONFIDENCE = {"high", "low"}


def parse_propose_action_output(raw_text: str) -> dict[str, Any]:
    """Parse and schema-validate one propose_action response.

    Reuses Member 2's parse_json_object() for JSON-object parsing, then
    checks it against the OUTPUT FORMAT contract in
    docs/prompts/propose_action/*.md. Raises ModelResponseError (already
    handled specially by generate_test_proposals) on any violation.
    """

    parsed = parse_json_object(raw_text)

    required_fields = ("action", "arguments", "rationale", "evidence", "confidence")
    missing = [field for field in required_fields if field not in parsed]
    if missing:
        raise ModelResponseError(
            f"Model output is missing required field(s): {', '.join(missing)}."
        )

    if parsed["action"] not in ALLOWED_ACTIONS:
        raise ModelResponseError(f"Model returned an unknown action: {parsed['action']!r}.")

    if parsed["confidence"] not in ALLOWED_CONFIDENCE:
        raise ModelResponseError(
            f"Model returned an unknown confidence value: {parsed['confidence']!r}."
        )

    if not isinstance(parsed["evidence"], list):
        raise ModelResponseError("Model 'evidence' field must be a list.")
    for entry in parsed["evidence"]:
        if not isinstance(entry, dict) or "source_path" not in entry:
            raise ModelResponseError(
                "Every evidence entry must be an object with a 'source_path'."
            )

    return parsed


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    description: str
    requirement_id: str
    requirement_text: str
    source_path: str
    source_text: str
    expected_actions: tuple[str, ...]
    expected_confidence: tuple[str, ...] | None
    disallowed_source_paths: tuple[str, ...]
    forbidden_text_substrings: tuple[str, ...]
    notes: str
    simulated_model_response: dict[str, Any]


def load_cases(path: Path = CASES_PATH) -> list[EvalCase]:
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        EvalCase(
            id=entry["id"],
            category=entry["category"],
            description=entry["description"],
            requirement_id=entry["requirement_id"],
            requirement_text=entry["requirement_text"],
            source_path=entry["source_path"],
            source_text=entry["source_text"],
            expected_actions=tuple(entry["expected_actions"]),
            expected_confidence=(
                tuple(entry["expected_confidence"])
                if entry.get("expected_confidence")
                else None
            ),
            disallowed_source_paths=tuple(entry.get("disallowed_source_paths", [])),
            forbidden_text_substrings=tuple(entry.get("forbidden_text_substrings", [])),
            notes=entry.get("notes", ""),
            simulated_model_response=entry["simulated_model_response"],
        )
        for entry in raw_cases
    ]
    if len(cases) != 10:
        raise ValueError(f"Expected exactly 10 evaluation cases, found {len(cases)}.")
    return cases


class ScriptedOfflineClient:
    """Deterministic stand-in for a real ModelClient, used for dry runs and CI.

    Returns each case's bundled "simulated_model_response" so the harness
    itself can be exercised end-to-end without network access or a paid API
    key. These are NOT real model outputs and must never be reported as the
    Week 2 live-model evaluation evidence.
    """

    def __init__(self, cases: list[EvalCase]) -> None:
        self._responses = {
            case.requirement_id: json.dumps(case.simulated_model_response)
            for case in cases
        }
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system_prompt: str, user_content: str) -> ModelCallResult:
        self.calls.append((system_prompt, user_content))
        payload = json.loads(user_content)
        requirement_id = payload.get("requirement", {}).get("id")
        raw_text = self._responses.get(requirement_id)
        if raw_text is None:
            raise ModelResponseError(
                f"No scripted offline response for requirement {requirement_id!r}."
            )
        return ModelCallResult(raw_text=raw_text, model="offline-fake-model", latency_ms=0)


@dataclass
class CaseResult:
    case: EvalCase
    passed: bool
    actual_action: str | None
    actual_confidence: str | None
    model: str | None
    latency_ms: int | None
    failure_reasons: list[str]


def evaluate_case(
    case: EvalCase,
    client: Any,
    system_prompt: str,
    prompt_version: str,
) -> CaseResult:
    proposal_input = ProposalInput(
        requirement_id=case.requirement_id,
        requirement_text=case.requirement_text,
        source_path=case.source_path,
        source_text=case.source_text,
    )

    try:
        result: PipelineResult = generate_test_proposals(
            proposal_input=proposal_input,
            system_prompt=system_prompt,
            prompt_version=prompt_version,
            client=client,
            response_parser=parse_propose_action_output,
        )
    except Exception as exc:  # noqa: BLE001 - any integration/response failure is a case result
        return CaseResult(
            case=case,
            passed=False,
            actual_action=None,
            actual_confidence=None,
            model=None,
            latency_ms=None,
            failure_reasons=[f"{type(exc).__name__}: {exc}"],
        )

    output = result.output
    actual_action = output.get("action")
    actual_confidence = output.get("confidence")
    rationale = str(output.get("rationale", ""))
    arguments_text = json.dumps(output.get("arguments", {}))
    evidence = output.get("evidence", [])

    failure_reasons: list[str] = []

    if actual_action not in case.expected_actions:
        failure_reasons.append(
            f"expected action in {list(case.expected_actions)}, got {actual_action!r}"
        )

    if case.expected_confidence and actual_confidence not in case.expected_confidence:
        failure_reasons.append(
            f"expected confidence in {list(case.expected_confidence)}, "
            f"got {actual_confidence!r}"
        )

    allowed_paths = {case.source_path, case.requirement_id}
    for entry in evidence:
        source_path = entry.get("source_path")
        if source_path in case.disallowed_source_paths:
            failure_reasons.append(
                f"cited a disallowed/fabricated source_path: {source_path!r}"
            )
        elif source_path not in allowed_paths:
            failure_reasons.append(
                f"evidence source_path {source_path!r} was not part of the "
                "context given this turn"
            )

    haystack = f"{rationale}\n{arguments_text}".lower()
    for phrase in case.forbidden_text_substrings:
        if phrase.lower() in haystack:
            failure_reasons.append(f"response contained forbidden text: {phrase!r}")

    return CaseResult(
        case=case,
        passed=not failure_reasons,
        actual_action=actual_action,
        actual_confidence=actual_confidence,
        model=result.model,
        latency_ms=result.latency_ms,
        failure_reasons=failure_reasons,
    )


def render_markdown_table(
    results: list[CaseResult],
    *,
    prompt_id: str,
    prompt_version: str,
    mode: str,
    model_label: str,
) -> str:
    passed = sum(1 for r in results if r.passed)
    lines = [
        f"# Week 2 Prompt Evaluation — `{prompt_id}` `{prompt_version}`",
        "",
        f"- Mode: **{mode}**"
        + (" (scripted responses — not real model evidence)" if mode == "offline" else ""),
        f"- Model: {model_label}",
        f"- Cases: {len(results)}",
        f"- Passed: {passed}/{len(results)}",
        "",
        "| Case | Category | Expected action(s) | Actual action | Expected confidence "
        "| Actual confidence | Result | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        expected_conf = ", ".join(r.case.expected_confidence) if r.case.expected_confidence else "any"
        notes = "; ".join(r.failure_reasons) if r.failure_reasons else r.case.notes
        lines.append(
            "| {id} | {cat} | {exp_a} | {act_a} | {exp_c} | {act_c} | {res} | {notes} |".format(
                id=r.case.id,
                cat=r.case.category,
                exp_a=", ".join(r.case.expected_actions),
                act_a=r.actual_action or "(error)",
                exp_c=expected_conf,
                act_c=r.actual_confidence or "-",
                res="PASS" if r.passed else "FAIL",
                notes=notes.replace("|", "/"),
            )
        )

    lines.append("")
    lines.append("## Case descriptions")
    lines.append("")
    for r in results:
        lines.append(f"- **{r.case.id}** ({r.case.category}): {r.case.description}")
    lines.append("")
    return "\n".join(lines)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["offline", "real"],
        default="offline",
        help="offline (default) scores bundled scripted responses; real calls "
        "the configured live model.",
    )
    parser.add_argument("--prompt-id", default="propose_action")
    parser.add_argument(
        "--prompt-version",
        default=None,
        help="Defaults to the latest version found under docs/prompts/<prompt-id>/.",
    )
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--endpoint", help="Chat-completions endpoint URL (real mode only).")
    parser.add_argument("--model", help="Model ID selected by Member 3 (real mode only).")
    parser.add_argument(
        "--api-key-env",
        default="MODEL_API_KEY",
        help="Environment variable holding the API key (real mode only). "
        "The key itself is never accepted as a command-line argument.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    cases = load_cases(args.cases)
    prompt = (
        load_prompt(args.prompt_id, args.prompt_version)
        if args.prompt_version
        else load_latest(args.prompt_id)
    )

    if args.mode == "real":
        if not args.endpoint or not args.model:
            raise SystemExit("--endpoint and --model are required in --mode real.")
        api_key = os.environ.get(args.api_key_env, "")
        if not api_key:
            raise SystemExit(
                f"Set the {args.api_key_env} environment variable before running --mode real."
            )
        client: Any = ChatCompletionsClient(
            endpoint_url=args.endpoint,
            api_key=api_key,
            model=args.model,
            timeout_seconds=args.timeout,
        )
        model_label = args.model
    else:
        client = ScriptedOfflineClient(cases)
        model_label = "offline-fake-model (scripted, not a real model run)"

    results = [
        evaluate_case(case, client, prompt.text, prompt.version) for case in cases
    ]
    report = render_markdown_table(
        results,
        prompt_id=prompt.prompt_id,
        prompt_version=prompt.version,
        mode=args.mode,
        model_label=model_label,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(report)

    passed = sum(1 for r in results if r.passed)
    print(f"\n{passed}/{len(results)} cases passed. Report written to {args.output}.")
    return 0


class OfflinePromptHarnessTests(unittest.TestCase):
    """CI-safe self-check: runs all ten cases against scripted responses.

    Two cases (adversarial_prompt_injection_in_requirement and
    adversarial_fabricated_citation_temptation) are red-team probes with a
    deliberately non-compliant scripted response, so they are EXPECTED to
    fail here. This proves the harness's grounding and injection checks
    actually catch bad behavior instead of rubber-stamping every response.
    Running against a real configured model (--mode real) is what produces
    the genuine Week 2 evaluation evidence.
    """

    EXPECTED_FAILURES = {
        "adversarial_prompt_injection_in_requirement",
        "adversarial_fabricated_citation_temptation",
    }

    def test_offline_harness_matches_expectations_for_every_case(self) -> None:
        cases = load_cases()
        self.assertEqual(len(cases), 10)

        prompt = load_latest("propose_action")
        client = ScriptedOfflineClient(cases)
        results = [
            evaluate_case(case, client, prompt.text, prompt.version) for case in cases
        ]

        actual_failures = {r.case.id for r in results if not r.passed}
        self.assertEqual(
            actual_failures,
            self.EXPECTED_FAILURES,
            "Offline self-check: exactly the two red-team probe cases should "
            "fail against their scripted non-compliant responses; every other "
            "case should pass.",
        )

    def test_every_case_response_is_schema_valid_json(self) -> None:
        cases = load_cases()
        client = ScriptedOfflineClient(cases)
        for case in cases:
            raw_text = client._responses[case.requirement_id]
            with self.subTest(case=case.id):
                parse_propose_action_output(raw_text)  # raises on schema violation


if __name__ == "__main__":
    sys.exit(main())
