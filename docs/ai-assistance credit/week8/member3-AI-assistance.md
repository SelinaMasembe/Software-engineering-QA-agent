## Week 8 AI assistance: Member 3 (AI Engineering Lead) (in progress)

**Status:** draft, in progress. Items marked TBC are not confirmed yet.

**Date:** 16th Oct 2026

**Deliverable:** prompt v1.3 (`docs/prompts/propose_action/v1.3.md`), memory block delimiter neutralisation in `src/rag/context_builder.py`, the ingested-content credential scan (`src/rag/credential_scan.py`), flagger tuning in `src/rag/injection_flagging.py`, and the real-model evaluation script (`scripts/real_model_eval.py`) with its first live runs.

**What I asked the AI for**

- Claude (claude.ai): TBC.
- Claude Code (Claude Opus 5.5):
  - writing prompt v1.3 and the reconciliation note
  - the memory delimiter and the credential scan
  - tuning the injection flagger
  - building the real-model evaluation script and its tests
  - analysing the live run
  - a read-only audit of my work to date
  - updating the Week 7 documents and drafting these Week 8 documents

**What the AI produced**

- **Prompt v1.3:** the FAILURE BEHAVIOR change, the reconciliation note, and three cases (ADV-EDG-04 to 06).
- **Memory delimiter:** the neutralisation in `build_context`, with one case (ADV-ADV-09).
- **Credential scan:** `src/rag/credential_scan.py` and its tests.
- **Flagger tuning:** five new rules and two narrowed rules, with the before and after measurements on the real corpus and on my labelled set.
- **Evaluation script:** `scripts/real_model_eval.py` and its tests, which use stub clients only, including the `--min-interval-seconds` option.
- **Analysis of the live trial run:** for each FAIL, whether it is a model error, a narrow expectation, or a harness limit.
- **The audit report**, the corrections to the Week 7 documents, and these drafts.

The flagger rules and their test cases were written by the same author, so passing them is not independent evidence. The real-model results are one run per case at temperature 0 on ten synthetic cases.

**Verification I performed myself**

- Ran the full suite in my own terminal (Claude Code reported 645 passed, 1 skipped, 619 subtests): [TO CONFIRM: yes or no, date, and my own output]
- Ran the dry run of `scripts/real_model_eval.py` before any live call: [TO CONFIRM: yes or no, and date]
- Ran the live trial and the partial run myself with `--live`: [TO CONFIRM: yes or no, and date]
- Read the `context_builder.py` and `credential_scan.py` diffs: [TO CONFIRM: yes or no, and date]
- Read the flagger rule changes and judged them against real requirement wording: [TO CONFIRM: yes or no, and date]
- Read the call records for the injection case and agreed it is a model error: [TO CONFIRM: yes or no, and date]
- Scanned changed files for hidden Unicode characters: [TO CONFIRM: yes or no, date, and my own output]
- Confirmed no API key appears in any run record or committed file: [TO CONFIRM: yes or no, and date]

**What I changed or would still change myself**

- The AI's editing tools inserted invisible characters again: escapes written as `\u` sequences were turned into literal zero-width, bidirectional, variation selector and line separator characters. Claude Code converted them back to visible escapes and checked the files were plain ASCII.
- The API key was in a file attached to the Claude panel. TBC: I replaced the key.
- I would still add independent injection cases from Member 4, the missing v1.1 calls and the v1.3 repeats, and a decision on the narrow Week 2 expectations.
- TBC: anything else I changed by hand.

**Not AI-generated**

- The choice of model (Gemini 2.5 Flash, from the Model Selection Note) and running the live calls with my own key.
- TBC: decisions I made myself this week.
- The team documents and code written by other members, which I read but did not write.

**Data sent to the AI**

- Claude Code had read and write access to the repository, so it saw the existing code, tests and documents.
- It did not read `.env`, and it did not print environment variables.
- TBC: what I pasted into Claude (claude.ai).

**Data sent to the model provider**

- Only the synthetic Week 2 case inputs and the prompt text were sent to Gemini.
- No personal or production data was sent.
- TBC: whether Google's free tier uses prompts and responses for training was not confirmed.

**Evidence status**

- Run records: `evidence/test-runs/week8/real-model/20261016T145654Z_live/` (trial) and `20261016T152707Z_live/` (partial). Not committed yet.
- The smoke run record is outside the repository. TBC: copied into `evidence/`.
- Terminal output of the full suite from my own terminal: TBC.
- Screenshot: TBC.

---
