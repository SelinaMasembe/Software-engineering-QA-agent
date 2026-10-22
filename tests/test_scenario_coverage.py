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
ALL_RUNTIME_STORIES = ACTIVE_STORIES | DEFERRED_STORIES

# These cases are intentionally not mapped to a user story. They validate the
# prompt/tool contract itself rather than a user-facing story.
UNMAPPED_CASES = {"failure_malformed_source_code"}

# The repo's traceability notes explicitly map edge_stub_implementation to both
# US-1 and US-2 because the stub itself is the grounded defect and the same
# propose_test action is how the gap surfaces in this prompt-only scope.
CASE_TO_STORIES = {
    "normal_clear_defect": {"US-1"},
    "normal_satisfied_requirement_regression": {"US-1"},
    "edge_stub_implementation": {"US-1", "US-2"},
    "edge_vague_requirement": {"US-7"},
    # This is indirect evidence for US-9's bounded-turn design, not evidence
    # that the iteration-cap halt itself has been implemented.
    "boundary_single_action_multiple_candidates": {"US-9"},
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


def mapping_errors(cases: list[dict], traceability_text: str) -> list[str]:
    """Return stale, incomplete, or undocumented traceability relationships."""
    errors: list[str] = []
    case_ids = [case["id"] for case in cases]
    case_id_set = set(case_ids)

    duplicate_case_ids = sorted(
        case_id for case_id in case_id_set if case_ids.count(case_id) > 1
    )
    if duplicate_case_ids:
        errors.append("duplicate fixture case IDs: " + ", ".join(duplicate_case_ids))

    mapped_case_ids = set(CASE_TO_STORIES)
    unknown_case_ids = sorted(mapped_case_ids - case_id_set)
    if unknown_case_ids:
        errors.append("mapping references unknown case IDs: " + ", ".join(unknown_case_ids))

    missing_case_ids = sorted(case_id_set - mapped_case_ids - UNMAPPED_CASES)
    if missing_case_ids:
        errors.append("fixture cases have no mapping or exception: " + ", ".join(missing_case_ids))

    unknown_stories = sorted(
        {story for stories in CASE_TO_STORIES.values() for story in stories}
        - ALL_RUNTIME_STORIES
    )
    if unknown_stories:
        errors.append("mapping references unknown user stories: " + ", ".join(unknown_stories))

    for case_id, stories in CASE_TO_STORIES.items():
        if case_id not in traceability_text:
            errors.append(f"{case_id} is missing from the traceability document")
        for story in stories:
            if story not in traceability_text:
                errors.append(f"{case_id} -> {story} is missing from the traceability document")

    for case_id in UNMAPPED_CASES:
        if case_id not in traceability_text:
            errors.append(f"unmapped exception {case_id} is missing from the traceability document")

    return errors


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
        else:
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

    def test_mapping_matches_fixture_and_traceability_document(self) -> None:
        traceability_text = TRACEABILITY_PATH.read_text(encoding="utf-8")
        self.assertEqual(mapping_errors(self.cases, traceability_text), [])

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

    def test_boundary_case_is_recorded_as_indirect_us_9_evidence(self) -> None:
        self.assertEqual(
            CASE_TO_STORIES["boundary_single_action_multiple_candidates"],
            {"US-9"},
        )


if __name__ == "__main__":
    cases = load_cases()
    print_coverage_report(cases)
    print("\nAutomated assertions:")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ScenarioCoverageTests)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
