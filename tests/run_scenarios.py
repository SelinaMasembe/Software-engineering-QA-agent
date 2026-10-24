#!/usr/bin/env python3
"""Run every evaluation scenario in one go and pull the results together.

Week 7, Member 5 (Task Allocation Plan: "Write the script that runs all
thirty-plus scenarios in one go and pulls the results together").

This runner owns no checks of its own. Each suite is run with the function
its owner already wrote, and only the results are combined:

==================  =========================  =====  =======================================
Suite               Owner                      Cases  Runs through
==================  =========================  =====  =======================================
``behaviour``       Member 3, Week 7           30     ``run_case`` + ``evaluation.scorer``
                                                      (real loop, router, gate, sandbox)
``prompt``          Member 4, Week 2           10     ``evaluate_case`` (scripted model)
``rag``             Member 4, Week 3           15     ``evaluate_case`` (real retrieval)
``failure_retest``  Member 4, Weeks 7-8        6      ``run_probe`` (current code)
==================  =========================  =====  =======================================

Every scenario gets one row: suite, ID, brief category, user stories, risk,
outcome (PASS, PARTIAL, FAIL), the outcome its owner expects, and whether
those match. A scenario whose owner *expects* a FAIL or PARTIAL (a red-team
probe the harness must catch, or a documented known gap) is reported as
behaving as expected, never silently turned into a PASS.

Nothing here calls a real model: the prompt cases use the scripted responses
bundled with them and the behaviour cases use a scripted planner. Real-model
evidence is recorded separately under ``evidence/test-runs/``.

Usage, from the repository root:

    python3 tests/run_scenarios.py                    # run all, write evidence
    python3 tests/run_scenarios.py --suite behaviour  # one suite (repeatable)
    python3 tests/run_scenarios.py --no-write         # print the summary only

Exit code 0 when every scenario behaved as its owner expects, 1 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SRC_DIR = REPO_ROOT / "src"
for _path in (SRC_DIR, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

DEFAULT_OUTPUT_DIR = REPO_ROOT / "evidence" / "evaluation"
OUTPUT_STEM = "week7-scenario-results"
SCHEMA = "qa-agent.scenario-run/v1"

#: The six scenario categories the Week 7 brief names (Member 3's names).
BRIEF_CATEGORIES = (
    "normal",
    "edge",
    "incorrect_information",
    "adversarial",
    "tool_failure",
    "unauthorized_action",
)
ALL_USER_STORIES = tuple(f"US-{number}" for number in range(1, 13))
OUTCOMES = ("PASS", "PARTIAL", "FAIL")

#: How the older suites' own category names map onto the brief's six. This
#: mapping is the runner's judgement and is stated here so it can be reviewed.
_PROMPT_CATEGORY = {
    "normal": "normal",
    "edge": "edge",
    "adversarial": "adversarial",
    "failure": "edge",  # malformed source input, not a tool failure
}
_RAG_CATEGORY = {
    "answerable": "normal",
    "partially_answerable": "edge",
    "unanswerable": "incorrect_information",  # asks for facts the corpus lacks
}


@dataclass(frozen=True)
class ScenarioResult:
    """One scenario's outcome in the combined table."""

    suite: str
    owner: str
    scenario_id: str
    title: str
    category: str  # one of BRIEF_CATEGORIES
    suite_category: str  # the suite's own category name
    user_stories: tuple[str, ...]
    risk_id: str
    outcome: str  # PASS | PARTIAL | FAIL
    expected_outcome: str  # what the suite's owner expects today
    reasons: tuple[str, ...] = ()
    duration_ms: int = 0

    @property
    def as_expected(self) -> bool:
        return self.outcome == self.expected_outcome

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["user_stories"] = list(self.user_stories)
        data["reasons"] = list(self.reasons)
        data["as_expected"] = self.as_expected
        return data


@dataclass
class SuiteRun:
    name: str
    owner: str
    results: list[ScenarioResult] = field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


# ---------------------------------------------------------------------------
# Suites. Each loader imports its owner's module and calls the owner's own
# run/score functions; nothing is re-implemented here.
# ---------------------------------------------------------------------------


def run_behaviour_suite() -> SuiteRun:
    """Member 3's adversarial and behaviour cases, scored by ``evaluation.scorer``."""

    from adversarial.fixtures import CASES
    from adversarial.test_adversarial_cases import run_case
    from evaluation.scorer import score_case, summarize

    run = SuiteRun("behaviour", "Member 3 (Week 7)")
    scores = []
    for case in CASES:
        started = time.perf_counter()
        score = score_case(case, run_case(case))
        scores.append(score)
        run.results.append(
            ScenarioResult(
                suite=run.name,
                owner=run.owner,
                scenario_id=case.case_id,
                title=case.title,
                category=case.category,
                suite_category=case.category,
                user_stories=(case.user_story,),
                risk_id=case.risk_id,
                outcome=score.outcome.value,
                expected_outcome="PARTIAL" if case.known_gap else "PASS",
                reasons=score.reasons,
                duration_ms=_ms(started),
            )
        )
    run.extra["scorer_summary"] = summarize(scores)
    return run


def run_prompt_suite() -> SuiteRun:
    """Member 4's ten prompt cases, offline against their scripted responses."""

    import test_prompt_harness as harness
    from test_scenario_coverage import CASE_TO_STORIES

    from prompts.loader import load_latest

    run = SuiteRun("prompt", "Member 4 (Week 2)")
    cases = harness.load_cases()
    prompt = load_latest("propose_action")
    client = harness.ScriptedOfflineClient(cases)
    red_team = harness.OfflinePromptHarnessTests.EXPECTED_FAILURES
    run.extra["prompt_version"] = prompt.version
    for case in cases:
        started = time.perf_counter()
        result = harness.evaluate_case(case, client, prompt.text, prompt.version)
        run.results.append(
            ScenarioResult(
                suite=run.name,
                owner=run.owner,
                scenario_id=case.id,
                title=case.description,
                category=_PROMPT_CATEGORY.get(case.category, "edge"),
                suite_category=case.category,
                user_stories=tuple(sorted(CASE_TO_STORIES.get(case.id, ()))),
                risk_id="",
                outcome="PASS" if result.passed else "FAIL",
                # A red-team probe's scripted response is deliberately bad,
                # so the harness is expected to FAIL it.
                expected_outcome="FAIL" if case.id in red_team else "PASS",
                reasons=tuple(result.failure_reasons),
                duration_ms=_ms(started),
            )
        )
    return run


def run_rag_suite() -> SuiteRun:
    """Member 4's fifteen retrieval cases against the fixture corpus."""

    import test_rag_eval as rag_eval

    run = SuiteRun("rag", "Member 4 (Week 3)")
    pipeline = rag_eval.build_pipeline()
    for case in rag_eval.load_cases():
        started = time.perf_counter()
        result = rag_eval.evaluate_case(case, pipeline)
        reasons = list(result.failure_reasons)
        if result.outcome == "PARTIAL" and case.known_limitation:
            reasons.append(f"known limitation: {case.known_limitation}")
        run.results.append(
            ScenarioResult(
                suite=run.name,
                owner=run.owner,
                scenario_id=case.id,
                title=case.query,
                category=_RAG_CATEGORY[case.category],
                suite_category=case.category,
                user_stories=(),
                risk_id="",
                outcome=result.outcome,
                expected_outcome="PARTIAL" if case.known_limitation else "PASS",
                reasons=tuple(reasons),
                duration_ms=_ms(started),
            )
        )
    return run


def run_failure_retest_suite() -> SuiteRun:
    """Member 4's five catalogued failures, re-tested against current code."""

    import test_failure_retest as retest

    run = SuiteRun("failure_retest", "Member 4 (Weeks 7-8)")
    for case_id, case in retest.CASES.items():
        started = time.perf_counter()
        probe = retest.run_probe(case_id)
        status = probe.get("status")
        run.results.append(
            ScenarioResult(
                suite=run.name,
                owner=run.owner,
                scenario_id=case_id,
                title=case["title"],
                category="adversarial",
                suite_category="regression",
                user_stories=(),
                risk_id="",
                outcome="PASS" if status == "pass" else "FAIL",
                expected_outcome="PASS",
                reasons=() if status == "pass" else (f"{status}: {probe.get('detail', '')}",),
                duration_ms=_ms(started),
            )
        )
    return run


SUITES: dict[str, Callable[[], SuiteRun]] = {
    "behaviour": run_behaviour_suite,
    "prompt": run_prompt_suite,
    "rag": run_rag_suite,
    "failure_retest": run_failure_retest_suite,
}


# ---------------------------------------------------------------------------
# Running and pulling results together.
# ---------------------------------------------------------------------------


def run_suites(
    names: list[str] | None = None,
    suites: dict[str, Callable[[], SuiteRun]] | None = None,
) -> list[SuiteRun]:
    """Run the named suites (default: all). A suite that crashes is recorded, not fatal."""

    suites = SUITES if suites is None else suites
    runs: list[SuiteRun] = []
    for name in names or list(suites):
        if name not in suites:
            raise ValueError(f"unknown suite {name!r}; choose from {sorted(suites)}")
        started = time.perf_counter()
        try:
            run = suites[name]()
        except Exception as error:  # report it as a broken suite, keep going
            run = SuiteRun(name, "unknown", error=f"{type(error).__name__}: {error}")
        run.duration_ms = _ms(started)
        runs.append(run)
    return runs


def build_report(runs: list[SuiteRun]) -> dict[str, Any]:
    """Combine suite runs into one machine-readable report."""

    results = [result for run in runs for result in run.results]
    outcomes = Counter(result.outcome for result in results)
    covered = sorted(
        {story for result in results for story in result.user_stories},
        key=lambda story: int(story.split("-")[1]),
    )
    by_category = {}
    for category in BRIEF_CATEGORIES:
        rows = [result for result in results if result.category == category]
        by_category[category] = {
            "scenarios": len(rows),
            **{outcome: sum(1 for row in rows if row.outcome == outcome) for outcome in OUTCOMES},
        }

    unexpected = [result for result in results if not result.as_expected]
    broken = [run for run in runs if run.error]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "model": "none: scripted planner and scripted prompt responses (offline)",
        "totals": {
            "scenarios": len(results),
            "outcomes": {outcome: outcomes.get(outcome, 0) for outcome in OUTCOMES},
            "as_expected": len(results) - len(unexpected),
            "unexpected": len(unexpected),
            "broken_suites": len(broken),
            "all_as_expected": not unexpected and not broken,
        },
        "suites": [
            {
                "suite": run.name,
                "owner": run.owner,
                "scenarios": len(run.results),
                "outcomes": {
                    outcome: sum(1 for r in run.results if r.outcome == outcome)
                    for outcome in OUTCOMES
                },
                "as_expected": sum(1 for r in run.results if r.as_expected),
                "duration_ms": run.duration_ms,
                "error": run.error,
                **run.extra,
            }
            for run in runs
        ],
        "by_category": by_category,
        "user_story_coverage": {
            "covered": covered,
            "not_covered": [story for story in ALL_USER_STORIES if story not in covered],
            "unmapped_scenarios": sum(1 for result in results if not result.user_stories),
        },
        "unexpected": [result.to_dict() for result in unexpected],
        "scenarios": [result.to_dict() for result in results],
    }


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


# ---------------------------------------------------------------------------
# Output.
# ---------------------------------------------------------------------------


def render_markdown(report: dict[str, Any]) -> str:
    totals = report["totals"]
    lines = [
        "# Week 7 Scenario Results",
        "",
        f"Generated {report['generated_at']} at commit `{report['git_head']}` by "
        "`tests/run_scenarios.py` (Member 5). Model: "
        f"{report['model']}.",
        "",
        "## Summary",
        "",
        f"- Scenarios run: **{totals['scenarios']}**",
        f"- Outcomes: PASS {totals['outcomes']['PASS']}, PARTIAL "
        f"{totals['outcomes']['PARTIAL']}, FAIL {totals['outcomes']['FAIL']}",
        f"- Behaved as their owner expects: **{totals['as_expected']} of "
        f"{totals['scenarios']}**; unexpected: {totals['unexpected']}; broken suites: "
        f"{totals['broken_suites']}",
        "",
        "| Suite | Owner | Scenarios | PASS | PARTIAL | FAIL | As expected | Time (ms) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for suite in report["suites"]:
        o = suite["outcomes"]
        name = suite["suite"] + (f" (error: {suite['error']})" if suite["error"] else "")
        lines.append(
            f"| {name} | {suite['owner']} | {suite['scenarios']} | {o['PASS']} | "
            f"{o['PARTIAL']} | {o['FAIL']} | {suite['as_expected']} | {suite['duration_ms']} |"
        )

    lines += ["", "## By brief category", "", "| Category | Scenarios | PASS | PARTIAL | FAIL |",
              "| --- | --- | --- | --- | --- |"]
    for category, row in report["by_category"].items():
        lines.append(
            f"| {category} | {row['scenarios']} | {row['PASS']} | {row['PARTIAL']} | {row['FAIL']} |"
        )

    behaviour = next((s for s in report["suites"] if s["suite"] == "behaviour"), None)
    if behaviour and "scorer_summary" in behaviour:
        summary = behaviour["scorer_summary"]
        lines += ["", "## Behaviour criteria (Member 3's scorer)", "",
                  "| Criterion | Passed | Total | Rate |", "| --- | --- | --- | --- |"]
        for name, row in summary["by_criterion"].items():
            lines.append(f"| {name} | {row['passed']} | {row['total']} | {row['rate']} |")
        lines += ["", f"Safety violations: {summary['safety_violations']} "
                  f"(unexpected: {summary['unexpected_safety_violations']})."]

    coverage = report["user_story_coverage"]
    lines += [
        "",
        "## User-story coverage",
        "",
        f"- Covered by at least one scenario: {', '.join(coverage['covered']) or 'none'}",
        f"- Not covered: {', '.join(coverage['not_covered']) or 'none'}",
        f"- Scenarios with no story mapped yet: {coverage['unmapped_scenarios']} "
        "(RAG and failure re-test cases carry no story mapping in their source files)",
    ]

    lines += ["", "## Scenarios not behaving as expected", ""]
    if report["unexpected"]:
        for row in report["unexpected"]:
            lines.append(
                f"- `{row['suite']}/{row['scenario_id']}`: got {row['outcome']}, expected "
                f"{row['expected_outcome']}. {'; '.join(row['reasons'])}"
            )
    else:
        lines.append("None.")

    lines += ["", "## All scenarios", "",
              "| Suite | Scenario | Category | Stories | Risk | Outcome | Expected | OK |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["scenarios"]:
        lines.append(
            f"| {row['suite']} | `{row['scenario_id']}` | {row['category']} | "
            f"{', '.join(row['user_stories']) or '-'} | {row['risk_id'] or '-'} | "
            f"{row['outcome']} | {row['expected_outcome']} | {'yes' if row['as_expected'] else '**no**'} |"
        )
    return "\n".join(lines) + "\n"


def render_csv(report: dict[str, Any]) -> str:
    buffer = io.StringIO()
    columns = ["suite", "owner", "scenario_id", "category", "suite_category", "user_stories",
               "risk_id", "outcome", "expected_outcome", "as_expected", "duration_ms", "reasons"]
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in report["scenarios"]:
        writer.writerow({
            **{key: row[key] for key in columns if key not in ("user_stories", "reasons")},
            "user_stories": " ".join(row["user_stories"]),
            "reasons": " | ".join(row["reasons"]),
        })
    return buffer.getvalue()


def write_outputs(report: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        output_dir / f"{OUTPUT_STEM}.json": json.dumps(report, indent=2) + "\n",
        output_dir / f"{OUTPUT_STEM}.md": render_markdown(report),
        output_dir / f"{OUTPUT_STEM}.csv": render_csv(report),
    }
    for path, text in paths.items():
        path.write_text(text, encoding="utf-8")
    return list(paths)


def print_summary(report: dict[str, Any], stream=None) -> None:
    stream = sys.stdout if stream is None else stream
    totals = report["totals"]
    print(f"Scenarios: {totals['scenarios']}  "
          f"PASS {totals['outcomes']['PASS']}  PARTIAL {totals['outcomes']['PARTIAL']}  "
          f"FAIL {totals['outcomes']['FAIL']}", file=stream)
    for suite in report["suites"]:
        status = f"ERROR {suite['error']}" if suite["error"] else (
            f"{suite['as_expected']}/{suite['scenarios']} as expected"
        )
        print(f"  {suite['suite']:<15} {suite['owner']:<18} {status}  ({suite['duration_ms']} ms)",
              file=stream)
    for row in report["unexpected"]:
        print(f"  UNEXPECTED {row['suite']}/{row['scenario_id']}: {row['outcome']} "
              f"(expected {row['expected_outcome']})", file=stream)
    verdict = "all scenarios behaved as expected" if totals["all_as_expected"] else (
        "SOME SCENARIOS DID NOT BEHAVE AS EXPECTED")
    print(f"Result: {verdict}", file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", action="append", choices=sorted(SUITES),
                        help="run only this suite (repeatable; default: all)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"where to write the results (default: {DEFAULT_OUTPUT_DIR.relative_to(REPO_ROOT)})")
    parser.add_argument("--no-write", action="store_true", help="print the summary without writing files")
    args = parser.parse_args(argv)

    report = build_report(run_suites(args.suite))
    print_summary(report)
    if not args.no_write:
        for path in write_outputs(report, args.output_dir):
            shown = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
            print(f"Wrote {shown}")
    return 0 if report["totals"]["all_as_expected"] else 1


if __name__ == "__main__":
    sys.exit(main())
