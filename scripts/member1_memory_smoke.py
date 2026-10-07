"""Member 1, Week 6: walk through the memory record by hand.

Run from the repository root:

    python scripts/member1_memory_smoke.py

Standard library only. Nothing is written to disk.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory import MEMORY_DESCRIPTION, ProposalMemoryRecord, make_proposal_key  # noqa: E402
from models.types import Confidence, EvidenceRef, TestProposal  # noqa: E402

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
CASES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "prompt_eval_cases.json"


def heading(text: str) -> None:
    print(f"\n=== {text} ===")


def main() -> int:
    heading("The sentence every document must carry")
    print(MEMORY_DESCRIPTION)

    heading("1. A real proposal becomes a record")
    case = next(c for c in json.loads(CASES.read_text(encoding="utf-8")) if c["id"] == "normal_clear_defect")
    response = case["simulated_model_response"]
    proposal = TestProposal(
        title=response["arguments"]["title"],
        target=response["arguments"]["target"],
        rationale=response["rationale"],
        evidence=tuple(EvidenceRef(source_path=e["source_path"]) for e in response["evidence"]),
        confidence=Confidence(response["confidence"]),
        requirement_id=case["requirement_id"],
    )
    record = ProposalMemoryRecord.from_test_proposal(
        module=case["source_path"], proposal=proposal, proposed_at=NOW
    )
    print(f"module={record.module} status={record.status.value} key={record.proposal_key}")
    print("rationale and evidence kept?", hasattr(record, "rationale") or hasattr(record, "evidence"))

    heading("2. The same idea, reworded trivially, gets the same key")
    again = make_proposal_key(
        "./pricing\\discount.py",
        title=proposal.title.upper() + "!",
        requirement_id=case["requirement_id"],
    )
    print("same key:", again == record.proposal_key)

    heading("3. A real paraphrase is NOT caught (documented limit)")
    paraphrase = make_proposal_key(
        case["source_path"],
        title="Negative percentages must not change the price",
        requirement_id=case["requirement_id"],
    )
    print("same key:", paraphrase == record.proposal_key)

    heading("4. Allowed moves")
    run = record.mark_run(at=NOW + timedelta(minutes=5), test_node_id="tests/test_discount.py::test_negative")
    print("after run:", run.status.value, run.run_at.isoformat())
    rejected = run.mark_rejected(by="reviewer-1", at=NOW + timedelta(minutes=10))
    print("after rejection:", rejected.status.value, "run history kept:", rejected.run_at is not None)

    heading("5. A rejection is final")
    for label, action in (
        ("run again", lambda: rejected.mark_run(at=NOW + timedelta(minutes=11))),
        ("reject again", lambda: rejected.mark_rejected(by="reviewer-2", at=NOW + timedelta(minutes=11))),
    ):
        try:
            action()
        except ValueError as exc:
            print(f"{label}: refused ({exc})")
        else:
            print(f"{label}: ALLOWED, this is a bug")
            return 1

    heading("6. JSON round trip, and nothing extra accepted")
    text = json.dumps(rejected.to_dict(), indent=2)
    print(text)
    print("round trip equal:", ProposalMemoryRecord.from_dict(json.loads(text)) == rejected)
    try:
        ProposalMemoryRecord.from_dict({**rejected.to_dict(), "diagnosis": "off by one"})
    except ValueError as exc:
        print("smuggled diagnosis field refused:", exc)
    else:
        print("diagnosis field ACCEPTED, this is a bug")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
