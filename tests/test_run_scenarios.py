"""Tests for Member 5's Week 7 scenario runner (tests/run_scenarios.py).

The runner is executed for real once (all four suites, about two seconds) and
its combined report is checked. Fake suites cover the aggregation rules: an
expected FAIL or PARTIAL stays as expected, an unexpected one or a crashed
suite fails the run.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_scenarios as runner  # noqa: E402


def fake_suite(*rows: tuple[str, str, str]) -> runner.SuiteRun:
    """rows: (scenario_id, outcome, expected_outcome)."""

    run = runner.SuiteRun("fake", "Tester")
    for scenario_id, outcome, expected in rows:
        run.results.append(
            runner.ScenarioResult(
                suite="fake",
                owner="Tester",
                scenario_id=scenario_id,
                title=scenario_id,
                category="normal",
                suite_category="normal",
                user_stories=("US-1",),
                risk_id="",
                outcome=outcome,
                expected_outcome=expected,
            )
        )
    return run


class RealRunTests(unittest.TestCase):
    """Run every real suite once and check the combined report."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.report = runner.build_report(runner.run_suites())

    def test_thirty_plus_scenarios_from_all_four_suites(self) -> None:
        totals = self.report["totals"]
        self.assertGreaterEqual(totals["scenarios"], 30)
        suites = {suite["suite"]: suite for suite in self.report["suites"]}
        self.assertEqual(set(suites), {"behaviour", "prompt", "rag", "failure_retest"})
        self.assertGreaterEqual(suites["behaviour"]["scenarios"], 30)
        self.assertEqual(suites["prompt"]["scenarios"], 10)
        self.assertEqual(suites["rag"]["scenarios"], 15)
        self.assertEqual(suites["failure_retest"]["scenarios"], 5)
        self.assertTrue(all(suite["error"] is None for suite in suites.values()))

    def test_every_scenario_behaves_as_its_owner_expects(self) -> None:
        self.assertEqual(self.report["unexpected"], [])
        self.assertTrue(self.report["totals"]["all_as_expected"])

    def test_every_brief_category_is_covered(self) -> None:
        for category in runner.BRIEF_CATEGORIES:
            with self.subTest(category=category):
                self.assertGreater(self.report["by_category"][category]["scenarios"], 0)

    def test_red_team_probes_are_expected_failures_not_passes(self) -> None:
        prompt = [row for row in self.report["scenarios"] if row["suite"] == "prompt"]
        fails = {row["scenario_id"] for row in prompt if row["outcome"] == "FAIL"}
        self.assertEqual(
            fails,
            {"adversarial_prompt_injection_in_requirement", "adversarial_fabricated_citation_temptation"},
        )
        self.assertTrue(all(row["as_expected"] for row in prompt))

    def test_known_gaps_stay_partial(self) -> None:
        partial = [row for row in self.report["scenarios"] if row["outcome"] == "PARTIAL"]
        self.assertTrue(partial)
        self.assertTrue(all(row["expected_outcome"] == "PARTIAL" for row in partial))

    def test_ids_are_unique_within_each_suite(self) -> None:
        keys = [(row["suite"], row["scenario_id"]) for row in self.report["scenarios"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_behaviour_suite_carries_the_scorer_summary(self) -> None:
        behaviour = next(s for s in self.report["suites"] if s["suite"] == "behaviour")
        self.assertEqual(behaviour["scorer_summary"]["cases"], behaviour["scenarios"])
        self.assertEqual(behaviour["scorer_summary"]["unexpected_safety_violations"], 0)

    def test_story_coverage_lists_every_story_once(self) -> None:
        coverage = self.report["user_story_coverage"]
        self.assertEqual(
            sorted(coverage["covered"] + coverage["not_covered"], key=lambda s: int(s[3:])),
            list(runner.ALL_USER_STORIES),
        )

    def test_report_is_json_serialisable_and_markdown_and_csv_render(self) -> None:
        json.dumps(self.report)
        markdown = runner.render_markdown(self.report)
        self.assertIn("# Week 7 Scenario Results", markdown)
        self.assertIn("ADV-NOR-01", markdown)
        rows = list(csv.DictReader(io.StringIO(runner.render_csv(self.report))))
        self.assertEqual(len(rows), self.report["totals"]["scenarios"])


class AggregationTests(unittest.TestCase):
    def report_for(self, *runs: runner.SuiteRun) -> dict:
        return runner.build_report(list(runs))

    def test_an_expected_fail_or_partial_is_still_as_expected(self) -> None:
        report = self.report_for(
            fake_suite(("a", "PASS", "PASS"), ("b", "FAIL", "FAIL"), ("c", "PARTIAL", "PARTIAL"))
        )
        self.assertTrue(report["totals"]["all_as_expected"])
        self.assertEqual(report["totals"]["outcomes"], {"PASS": 1, "PARTIAL": 1, "FAIL": 1})

    def test_an_unexpected_outcome_fails_the_run(self) -> None:
        report = self.report_for(fake_suite(("a", "FAIL", "PASS"), ("b", "PASS", "PARTIAL")))
        self.assertFalse(report["totals"]["all_as_expected"])
        self.assertEqual([row["scenario_id"] for row in report["unexpected"]], ["a", "b"])

    def test_a_crashing_suite_is_recorded_and_fails_the_run(self) -> None:
        def broken():
            raise RuntimeError("fixture missing")

        runs = runner.run_suites(suites={"broken": broken, "ok": lambda: fake_suite(("a", "PASS", "PASS"))})
        report = runner.build_report(runs)
        self.assertEqual(report["totals"]["broken_suites"], 1)
        self.assertFalse(report["totals"]["all_as_expected"])
        self.assertIn("RuntimeError", report["suites"][0]["error"])

    def test_unknown_suite_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            runner.run_suites(["nope"])


class CommandLineTests(unittest.TestCase):
    def run_main(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = runner.main(list(args))
        return code, output.getvalue()

    def test_writes_json_markdown_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_main("--suite", "rag", "--suite", "prompt", "--output-dir", directory)
            self.assertEqual(code, 0)
            written = sorted(path.name for path in Path(directory).iterdir())
            self.assertEqual(
                written,
                [f"{runner.OUTPUT_STEM}.csv", f"{runner.OUTPUT_STEM}.json", f"{runner.OUTPUT_STEM}.md"],
            )
            data = json.loads((Path(directory) / f"{runner.OUTPUT_STEM}.json").read_text(encoding="utf-8"))
            self.assertEqual(data["totals"]["scenarios"], 25)
        self.assertIn("all scenarios behaved as expected", output)

    def test_no_write_prints_without_creating_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_main("--suite", "rag", "--no-write", "--output-dir", directory)
            self.assertEqual(code, 0)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertIn("Scenarios: 15", output)

    def test_exit_code_is_one_when_something_is_unexpected(self) -> None:
        original = runner.SUITES
        try:
            runner.SUITES = {"fake": lambda: fake_suite(("a", "FAIL", "PASS"))}
            code, output = self.run_main("--no-write")
        finally:
            runner.SUITES = original
        self.assertEqual(code, 1)
        self.assertIn("UNEXPECTED fake/a", output)


if __name__ == "__main__":
    unittest.main()
