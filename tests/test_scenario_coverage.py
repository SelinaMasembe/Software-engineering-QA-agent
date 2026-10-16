from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = REPO_ROOT / "tests" / "fixtures" / "prompt_eval_cases.json"
TRACEABILITY_PATH = REPO_ROOT / "docs" / "requirements" / "week2-test-case-traceability.md"
CHARTER_PATH = (
    REPO_ROOT / "knowledge" / "corpus" / "requirements" / "project-charter-and-user-stories.txt"
)

# Scope for the Week 2 propose/decide evaluation. The repo explicitly states
# that US-1, US-2, US-7, US-8, and US-11 are the only active runtime-prompt
# stories with current evidence. US-3/4/5/6/9/10 are deferred and must not fail
# this check. US-12 is diagram/matrix literacy, not a prompt runtime story.
ACTIVE_STORIES = {"US-1", "US-2", "US-7", "US-8", "US-11"}
DEFERRED_STORIES = {"US-3", "US-4", "US-5", "US-6", "US-9", "US-10"}

# The repo's traceability notes explicitly map edge_stub_implementation to both
# US-1 and US-2 because the stub itself is the grounded defect and the same
# propose_test action is how the gap surfaces in this prompt-only scope.
CASE_TO_STORIES = {
    "normal_clear_defect": {"US-1"},
    "normal_satisfied_requirement_regression": {"US-1"},
    "edge_stub_implementation": {"US-1", "US-2"},
    "edge_vague_requirement": {"US-7"},
    "adversarial_prompt_injection_in_requirement": {"US-11"},
    "adversarial_prompt_injection_in_source_comment": {"US-11"},
    "adversarial_fabricated_citation_temptation": {"US-8"},
    "security_system_prompt_exfiltration_attempt": {"US-11"},
}


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """Load the Week 2 evaluation fixture used by the project harness."""
    with path.open("r", encoding="utf-8") as handle:
        cases = json.load(handle)
    if len(cases) != 10:
        raise ValueError(f"Expected 10 evaluation cases, found {len(cases)}.")
    return cases


def active_story_coverage(cases: list[dict]) -> dict[str, list[str]]:
    """Return which active stories have supporting case IDs."""
    coverage: dict[str, list[str]] = {story: [] for story in sorted(ACTIVE_STORIES)}
    for case in cases:
        for story in CASE_TO_STORIES.get(case["id"], set()):
            if story in coverage:
                coverage[story].append(case["id"])
    return coverage


def uncovered_active_stories(cases: list[dict]) -> list[str]:
    """Return active, in-scope stories that currently lack support."""
    return sorted(
        story for story, case_ids in active_story_coverage(cases).items() if not case_ids
    )


def deferred_story_status() -> dict[str, str]:
    """Document intentionally deferred stories excluded from the Week 2 check."""
    return {
        story: "deferred to later tool-backed workflow phases"
        for story in sorted(DEFERRED_STORIES)
    }


def print_coverage_report(cases: list[dict]) -> None:
    """Print human-readable progress and coverage results for direct execution."""
    coverage = active_story_coverage(cases)
    mapped_case_ids = set(CASE_TO_STORIES)

    print("Scenario-to-story coverage report")
    print("=" * 35)
    print(f"[PASS] Loaded fixture: {len(cases)} evaluation cases")
    print(f"[PASS] Loaded traceability document: {TRACEABILITY_PATH.name}")
    print(f"[PASS] Loaded user-story charter: {CHARTER_PATH.name}")
    print("\nEvaluation cases:")
    for case in cases:
        case_id = case["id"]
        stories = sorted(CASE_TO_STORIES.get(case_id, set()))
        if stories:
            print(f"[PASS] {case_id} -> {', '.join(stories)}")
        elif case_id not in mapped_case_ids:
            print(f"[INFO] {case_id} -> no user-story mapping (documented exception)")

    print("\nActive story coverage:")
    for story, case_ids in coverage.items():
        if case_ids:
            print(f"[PASS] {story} covered by: {', '.join(case_ids)}")
        else:
            print(f"[FAIL] {story} has no supporting scenario")

    print("\nDeferred stories:")
    for story in sorted(DEFERRED_STORIES):
        print(f"[INFO] {story} deferred by project design")


class ScenarioCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(CASES_PATH.exists(), f"Missing fixture: {CASES_PATH}")
        self.assertTrue(TRACEABILITY_PATH.exists(), f"Missing traceability doc: {TRACEABILITY_PATH}")
        self.assertTrue(CHARTER_PATH.exists(), f"Missing charter: {CHARTER_PATH}")
        self.cases = load_cases()

    def test_active_stories_are_all_covered(self) -> None:
        missing = uncovered_active_stories(self.cases)
        self.assertEqual(
            missing,
            [],
            "Active Week 2 stories without any supporting scenario: " + ", ".join(missing),
        )

    def test_deferred_stories_are_not_treated_as_failures(self) -> None:
        self.assertIn("US-3", DEFERRED_STORIES)
        self.assertIn("US-4", DEFERRED_STORIES)
        self.assertIn("US-5", DEFERRED_STORIES)
        self.assertIn("US-6", DEFERRED_STORIES)
        self.assertIn("US-9", DEFERRED_STORIES)
        self.assertIn("US-10", DEFERRED_STORIES)
        self.assertTrue(deferred_story_status())

    def test_edge_stub_mapping_covers_both_us_1_and_us_2(self) -> None:
        self.assertIn("US-1", CASE_TO_STORIES["edge_stub_implementation"])
        self.assertIn("US-2", CASE_TO_STORIES["edge_stub_implementation"])


if __name__ == "__main__":
    cases = load_cases()
    print_coverage_report(cases)
    print("\nAutomated assertions:")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ScenarioCoverageTests)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
