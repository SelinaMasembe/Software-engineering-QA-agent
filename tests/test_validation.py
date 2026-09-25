from __future__ import annotations

import json
import unittest
from pathlib import Path

from models.types import Action, Confidence, EvidenceRef, ProposalSet, UntraceableProposalError
from orchestration.validation import validate_citations

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PROMPT_EVAL_CASES_PATH = FIXTURES_DIR / "prompt_eval_cases.json"


def make_proposal(
    action: Action = Action.SEARCH_REPO,
    evidence: tuple[EvidenceRef, ...] = (EvidenceRef(source_path="src/app.py"),),
) -> ProposalSet:
    return ProposalSet(
        action=action,
        arguments={"query": "login"},
        rationale="Find the login handler.",
        evidence=evidence,
        confidence=Confidence.HIGH,
    )


class ValidateCitationsTests(unittest.TestCase):
    def test_valid_citation_passes_through_unchanged(self) -> None:
        proposal = make_proposal()

        result = validate_citations(proposal, allowed_source_paths={"src/app.py"})

        self.assertIs(result, proposal)

    def test_empty_evidence_is_rejected(self) -> None:
        proposal = make_proposal(evidence=())

        with self.assertRaisesRegex(UntraceableProposalError, "no\\s+evidence"):
            validate_citations(proposal, allowed_source_paths={"src/app.py"})

    def test_fabricated_source_path_is_rejected(self) -> None:
        proposal = make_proposal(
            evidence=(EvidenceRef(source_path="pricing/discount_table.md"),)
        )

        with self.assertRaisesRegex(
            UntraceableProposalError, "pricing/discount_table.md"
        ):
            validate_citations(proposal, allowed_source_paths={"shipping/cost.py"})

    def test_one_fabricated_entry_among_valid_ones_still_rejects(self) -> None:
        proposal = make_proposal(
            evidence=(
                EvidenceRef(source_path="src/app.py"),
                EvidenceRef(source_path="src/nonexistent.py"),
            )
        )

        with self.assertRaises(UntraceableProposalError):
            validate_citations(
                proposal, allowed_source_paths={"src/app.py", "src/other.py"}
            )

    def test_applies_to_every_action_not_only_propose_test(self) -> None:
        # US-8's check is not scoped to propose_test: propose_action v1.1
        # requires "evidence" on every response, and Member 2's boundary
        # validates citations before any tool dispatch, so search_repo,
        # read_file, run_tests and draft_issue proposals are all covered.
        for action in (
            Action.SEARCH_REPO,
            Action.READ_FILE,
            Action.RUN_TESTS,
            Action.DRAFT_ISSUE,
            Action.PROPOSE_TEST,
            Action.NO_ACTION,
        ):
            with self.subTest(action=action):
                proposal = make_proposal(action=action, evidence=())
                with self.assertRaises(UntraceableProposalError):
                    validate_citations(proposal, allowed_source_paths={"src/app.py"})

    def test_returns_proposal_without_mutating_it(self) -> None:
        proposal = make_proposal()
        original_evidence = proposal.evidence

        validate_citations(proposal, allowed_source_paths={"src/app.py", "extra.py"})

        self.assertEqual(proposal.evidence, original_evidence)


class RealFixtureCaseTests(unittest.TestCase):
    """Runs the check against the real red-team fixture the harness already
    uses, instead of only a hand-built example, so this proves something
    about the actual evaluation data rather than an artificial case."""

    def setUp(self) -> None:
        if not PROMPT_EVAL_CASES_PATH.exists():
            self.skipTest(f"{PROMPT_EVAL_CASES_PATH} not found.")
        with PROMPT_EVAL_CASES_PATH.open(encoding="utf-8") as handle:
            self.cases = {case["id"]: case for case in json.load(handle)}

    def _proposal_from_case(self, case: dict) -> ProposalSet:
        raw = json.dumps(case["simulated_model_response"])
        return ProposalSet.model_validate_json(raw)

    def test_fabricated_citation_case_is_rejected(self) -> None:
        case = self.cases["adversarial_fabricated_citation_temptation"]
        proposal = self._proposal_from_case(case)
        # Only the case's own source_path was actually supplied this turn;
        # discount_table.md (what the scripted response cites) was not.
        allowed_source_paths = {case["source_path"]}

        with self.assertRaisesRegex(
            UntraceableProposalError, "discount_table.md"
        ):
            validate_citations(proposal, allowed_source_paths)

    def test_clean_grounded_case_passes(self) -> None:
        case = self.cases["normal_clear_defect"]
        proposal = self._proposal_from_case(case)
        allowed_source_paths = {case["source_path"]}

        result = validate_citations(proposal, allowed_source_paths)

        self.assertIs(result, proposal)


if __name__ == "__main__":
    unittest.main()
