import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from models.types import Action, ProposalSet, TestProposal, UntraceableProposalError

cases = json.loads((Path(__file__).parent / "tests/fixtures/prompt_eval_cases.json").read_text())

print(f"Loaded {len(cases)} real cases from Mustafa's fixture.\n")

for case in cases:
    raw = json.dumps(case["simulated_model_response"])
    proposal_set = ProposalSet.model_validate_json(raw)
    assert proposal_set.action.value == case["simulated_model_response"]["action"]

    line = f"{case['id']:45s} action={proposal_set.action.value:15s}"

    if proposal_set.action is Action.PROPOSE_TEST:
        tp = TestProposal.from_proposal_set(proposal_set, requirement_id=case["requirement_id"])
        allowed = {case["source_path"]}
        try:
            tp.validate_sources(allowed)
            line += " -> TestProposal OK, sources valid"
        except UntraceableProposalError as exc:
            line += f" -> TestProposal REJECTED ({exc})"[:120]
    else:
        line += " -> (not a test proposal, no TestProposal built)"

    print(line)

print("\nAll 10 cases parsed through ProposalSet.model_validate_json without error.")
print("Confirming the fabricated-citation case is actually caught by validate_sources:")

fab_case = next(c for c in cases if c["id"] == "adversarial_fabricated_citation_temptation")
raw = json.dumps(fab_case["simulated_model_response"])
ps = ProposalSet.model_validate_json(raw)
tp = TestProposal.from_proposal_set(ps, requirement_id=fab_case["requirement_id"])
try:
    tp.validate_sources({fab_case["source_path"]})  # discount_table.md is NOT in this set
    print("FAIL: expected UntraceableProposalError, none was raised")
except UntraceableProposalError as exc:
    print(f"OK: correctly rejected -> {exc}")
