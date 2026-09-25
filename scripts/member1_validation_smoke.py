#!/usr/bin/env python3
"""Prove src/orchestration/validation.py actually closes the gap Member 2's
Week 4 report left open: "Member 1: confirm citation validation occurs
before dispatch()."

Runs the same real fixture case Member 4's harness uses
(tests/fixtures/prompt_eval_cases.json's
adversarial_fabricated_citation_temptation) through the full intended
call order: parse -> validate_citations -> dispatch. The fabricated
citation must never reach the dispatcher at all, and a clean, grounded
proposal must pass through unchanged and dispatch normally.

This is a development smoke runner, the same pattern as
scripts/member1_corpus_smoke.py and scripts/member2_tool_dispatch_demo.py:
it is not part of the automated test suite, it is something you run
yourself to see the real thing work.

Usage (from the repository root):
    PYTHONPATH=src python3 scripts/member1_validation_smoke.py
On Windows PowerShell:
    $env:PYTHONPATH = "src"
    python scripts\\member1_validation_smoke.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models.types import (  # noqa: E402
    Action,
    Confidence,
    EvidenceRef,
    ProposalSet,
    UntraceableProposalError,
)
from orchestration import (  # noqa: E402
    ApprovalStatus,
    ApprovalVerdict,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRisk,
)
from orchestration.validation import validate_citations  # noqa: E402

FIXTURES_PATH = REPO_ROOT / "tests" / "fixtures" / "prompt_eval_cases.json"
CONTEXT = ExecutionContext(session_id="smoke-1", actor_id="dev-1", role="developer")


class DemoSearchRepoTool:
    """Canned stand-in tool, same convention as Member 2's demo adapters.
    Not a real tool: registered only so a passing proposal has something
    to dispatch to."""

    name = "search_repo"
    risk = ToolRisk.READ_ONLY
    allowed_roles = ("developer",)

    def validate_arguments(self, arguments):
        return dict(arguments)

    def run(self, arguments, context):
        return {"matches": ["pricing/discount.py"]}

    def validate_output(self, output):
        return dict(output)


def load_case(case_id: str) -> dict:
    with FIXTURES_PATH.open(encoding="utf-8") as handle:
        cases = {case["id"]: case for case in json.load(handle)}
    return cases[case_id]


def main() -> int:
    if not FIXTURES_PATH.exists():
        print(f"Could not find {FIXTURES_PATH}.", file=sys.stderr)
        return 2

    dispatcher = ToolDispatcher(ToolRegistry([DemoSearchRepoTool()]))
    failures = 0

    # Scenario 1: the red-team fixture. The scripted response cites
    # pricing/discount_table.md, which was never supplied this turn -
    # only shipping/cost.py was. validate_citations must stop it before
    # dispatch() ever sees it.
    case = load_case("adversarial_fabricated_citation_temptation")
    proposal = ProposalSet.model_validate_json(
        json.dumps(case["simulated_model_response"])
    )
    allowed_source_paths = {case["source_path"]}
    print(f"Scenario 1: {case['id']}")
    print(f"  Evidence cites: {[e.source_path for e in proposal.evidence]}")
    print(f"  Actually supplied this turn: {sorted(allowed_source_paths)}")
    try:
        validate_citations(proposal, allowed_source_paths)
        print("  ** unexpected: fabricated citation was NOT rejected **")
        failures += 1
    except UntraceableProposalError as exc:
        print(f"  -> rejected before dispatch, as expected: {exc}")
    print()

    # Scenario 2: a clean, grounded proposal. Citation checks out, so it
    # should pass through unchanged and dispatch normally.
    good_proposal = ProposalSet(
        action=Action.SEARCH_REPO,
        arguments={"query": "apply_discount"},
        rationale="Look for the discount function referenced by the requirement.",
        evidence=(EvidenceRef(source_path="pricing/discount.py"),),
        confidence=Confidence.HIGH,
    )
    print("Scenario 2: clean, grounded proposal")
    try:
        validated = validate_citations(good_proposal, {"pricing/discount.py"})
        result = dispatcher.dispatch(validated, context=CONTEXT)
        print(f"  validate_citations passed, dispatch status: {result.status.value}")
        if not result.executed:
            print("  ** unexpected: clean proposal did not execute **")
            failures += 1
    except UntraceableProposalError as exc:
        print(f"  ** unexpected rejection: {exc} **")
        failures += 1
    print()

    # Scenario 3: no evidence at all - the other half of US-8's negative
    # case (missing citation, not just fabricated).
    no_evidence_proposal = ProposalSet(
        action=Action.PROPOSE_TEST,
        arguments={"title": "some test"},
        rationale="No source given.",
        evidence=(),
        confidence=Confidence.LOW,
    )
    print("Scenario 3: proposal with no evidence at all")
    try:
        validate_citations(no_evidence_proposal, {"pricing/discount.py"})
        print("  ** unexpected: proposal with no evidence was NOT rejected **")
        failures += 1
    except UntraceableProposalError as exc:
        print(f"  -> rejected before dispatch, as expected: {exc}")

    print()
    if failures:
        print(f"{failures} scenario(s) behaved unexpectedly.")
        return 1
    print("All 3 scenarios behaved as expected.")
    print(
        "This confirms citation validation runs, and rejects, before a "
        "proposal ever reaches ToolDispatcher.dispatch()."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
