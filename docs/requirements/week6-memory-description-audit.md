# Week 6 Memory Description Audit (Member 1, Project/Requirements Lead)

Purpose: fix one sentence describing what the agent remembers, make every document say the same thing, and define the memory record in code so the sentence and the code cannot drift apart.

## 1. The finalised sentence

> The agent remembers, for each repository module, which tests it has proposed, which of those were run, and which a human explicitly rejected, so that it never repeats a proposal a developer has already seen or declined; it does not remember or reuse past diagnoses.

The sentence lives in code as `MEMORY_DESCRIPTION` in `src/memory/schema.py`. A test checks that it still contains every promise (per module, proposed, run, rejected by a human, never repeats, no diagnoses). Documents should copy it word for word.

## 2. What the record stores, and what it refuses to store

One frozen record per proposal. It stores exactly: module, proposal key, title, requirement ID (optional), target (optional), status, and per-stage timestamps (proposed, run, rejected), plus who rejected it and the test node ID if the test was run.

It has no field for diagnoses, tool output, evidence text, rationale, or free-form notes. `from_dict` rejects any extra field, and a guard test fails if the field set changes, so widening memory beyond the sentence needs a deliberate, visible edit.

Status moves: PROPOSED to RUN, and PROPOSED or RUN to REJECTED_BY_HUMAN. A rejection is final.

## 3. Wording found in each document

| Document | Owner | Current wording | Action |
|---|---|---|---|
| Project charter, Scope item v | Member 1 | Two sentences, same promises, "per repository module" and "as evidence in future reasoning" | **Changed by Member 1** to the one-sentence form above, prefixed "One justified persistent-memory use case:" |
| Week 1 quality and security documentation, AI Boundary Matrix row | Owner of that document (confirm) | "Retain memory of which tests were already proposed, run, or explicitly rejected for a given module. Does not retain or reuse past diagnoses." Status "Limited" | **Teammate to change**: replace with the sentence above. Keep "Limited". |
| Prompt Specification, "Memory" line (appears twice) | Owner of the prompt specification (likely Member 3) | "Memory: which tests were already proposed, run, or rejected for this module." Drops "by a human" | **Teammate to change**: "Memory: which tests this module has already had proposed, run, or explicitly rejected by a human. Never repeat these. Past diagnoses are not remembered." |
| Member 3 AI Engineering deliverables | Member 3 | "Which tests have already been proposed, run, or rejected for this module, from the memory store" | **Teammate to change**: add "explicitly rejected by a human" and "never repeat them". |
| Week 5 group report | Team | Says Week 6 adds "one justified persistent-memory use case" | No change needed, but the Week 6 report should quote the sentence above. |
| README, row 6 (Memory, state, interoperability) | Team | "Upcoming" | Update status when the store and wiring are done. |

I have not edited other members' documents. If you want me to apply the replacements, say so and I will.

## 4. Open items for the team

1. **Retention.** The boundary matrix has an open item on how long memory is kept, and User Story 10 notes it too. The schema deliberately does not hard-code a period. Recommended answer: kept until a human clears it. Needs a team decision and then one line in the charter.
2. **Paraphrases are not caught.** The proposal key matches the same module, anchor (requirement ID, else target, else none), and title after normalising case, punctuation, and spacing. A reworded title is a different key. This is a known limit. The prompt should also show the model its earlier proposals for the module; the key is the deterministic backstop, not the whole defence. The key needs all three parts to match exactly.
3. **`MemoryEntry` in `src/models/types.py`** (Week 2) is thinner than the new record and is not used anywhere. It is left untouched so no one's imports break. Recommend retiring it once the store uses `ProposalMemoryRecord`.
4. **Not built yet, and not Member 1's part:** the store that saves and loads records (the team convention is JSON files, as in `JSONApprovalStore`), and wiring into the agent's context and its approval and rejection handling. `to_dict` and `from_dict` are ready for it.

## 5. Verification

`tests/test_memory_schema.py` (31 tests) covers module normalisation, key stability and difference, record validation, transitions, immutability, JSON round trip, and the field-set guard. `scripts/member1_memory_smoke.py` shows the behaviour on a real proposal from the evaluation fixtures.
