#!/usr/bin/env python3
"""Run src/models/types.py against Member 4's real Week 2 evaluation cases.

This is a development smoke runner (see scripts/member2_model_smoke.py for
the equivalent for Member 2's model integration), not part of the automated
test suite. It answers one question: does the domain model Member 1 wrote
actually work against the ten real cases Member 4 designed, not just against
made-up examples?

For each of the ten cases in tests/fixtures/prompt_eval_cases.json, this
script:
  1. Parses the case's "simulated_model_response" through
     ProposalSet.model_validate_json (the exact hook
     src/rag/pipeline.py's generate_test_proposals() docstring names).
  2. If the action was "propose_test", builds a TestProposal from it and
     runs validate_sources() against the one source_path the case actually
     supplied - this is US-8's "reject a fabricated or missing citation"
     rule, enforced in code rather than only requested in the prompt.
  3. Prints what happened to every case, so a fabricated-citation rejection
     shows up as a clearly-labelled REJECTED line, not a crash.

Usage:
    python scripts/member1_types_smoke.py
(No PYTHONPATH setup needed - this script adds src/ to sys.path itself.)
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
    ProposalSet,
    TestProposal,
    UntraceableProposalError,
)

CASES_PATH = REPO_ROOT / "tests" / "fixtures" / "prompt_eval_cases.json"


def main() -> int:
    if not CASES_PATH.exists():
        print(f"Could not find {CASES_PATH} - run this from the repo root.", file=sys.stderr)
        return 2

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(cases)} real cases from {CASES_PATH.relative_to(REPO_ROOT)}\n")

    rejected_count = 0
    for case in cases:
        raw = json.dumps(case["simulated_model_response"])
        proposal_set = ProposalSet.model_validate_json(raw)

        line = f"{case['id']:45s} action={proposal_set.action.value:12s}"

        if proposal_set.action is Action.PROPOSE_TEST:
            test_proposal = TestProposal.from_proposal_set(
                proposal_set, requirement_id=case["requirement_id"]
            )
            allowed_source_paths = {case["source_path"]}
            try:
                test_proposal.validate_sources(allowed_source_paths)
                line += " -> TestProposal OK, sources valid"
            except UntraceableProposalError as exc:
                rejected_count += 1
                line += f" -> REJECTED: {exc}"
        else:
            line += " -> (not a test proposal)"

        print(line)

    print(
        f"\nAll {len(cases)} cases parsed through ProposalSet.model_validate_json "
        "without a crash."
    )
    print(
        f"{rejected_count} proposal(s) were rejected by validate_sources() - "
        "check above that this matches the fabricated-citation case in "
        "docs/evaluation/week2-ten-case-evaluation.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
