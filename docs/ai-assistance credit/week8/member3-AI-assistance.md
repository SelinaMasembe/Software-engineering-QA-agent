## Week 8 AI assistance: Member 3 (AI Engineering Lead)

**Date:** 16th Oct 2026

**Deliverable:** prompt v1.3 (`docs/prompts/propose_action/v1.3.md`), memory block delimiter neutralisation in `src/rag/context_builder.py`, the ingested-content credential scan (`src/rag/credential_scan.py`), flagger tuning in `src/rag/injection_flagging.py`, and the real-model evaluation script (`scripts/real_model_eval.py`) with its first live runs.

**What I asked the AI for**

- Claude Code (Claude Opus 5.5):
  - writing prompt v1.3 and the reconciliation note
  - the memory delimiter and the credential scan
  - tuning the injection flagger
  - building the real-model evaluation script and its tests
  - analysing the live run
  - a read-only audit of my work to date
  - updating the Week 7 documents and drafting these Week 8 documents
  - building the real ContextSensor and Planner, the history guard and the end-to-end session script, with their tests
  - fitting the sensor and planner to the loop's flag recording: the loop records sensed-context flags through `flag_trace_entry`, as merged on main, so the sensor and planner add no recording of their own for the sensed context; the planner still traces flags it finds in earlier tool output (history guard), because the loop never sees those

**What the AI produced**

- **Prompt v1.3:** the FAILURE BEHAVIOR change, the reconciliation note, and three cases (ADV-EDG-04 to 06).
- **Memory delimiter:** the neutralisation in `build_context`, with one case (ADV-ADV-09).
- **Credential scan:** `src/rag/credential_scan.py` and its tests.
- **Flagger tuning:** five new rules and two narrowed rules, with the before and after measurements on the real corpus and on my labelled set.
- **Evaluation script:** `scripts/real_model_eval.py` and its tests, which use stub clients only, including the `--min-interval-seconds` option.
- **Analysis of the live trial run:** for each FAIL, whether it is a model error, a narrow expectation, or a harness limit.
- **The audit report**, the corrections to the Week 7 documents, and these drafts.
- **Sensor and planner:** `src/agent/sensor.py`, `src/agent/planner.py`, `src/agent/history_guard.py`, `scripts/run_agent_session.py`, and their tests (written first, shown failing, then passing). Every test uses a stub model client; no live call was made.

The flagger rules and their test cases were written by the same author, so passing them is not independent evidence. The real-model results are one run per case at temperature 0 on ten synthetic cases.

**Verification I performed myself**

- Ran the full suite in my own terminal (678 passed, 1 skipped, 6 warnings in 79.62s (0:01:19)): yes
- Ran the dry run of `scripts/real_model_eval.py` (stub client, no network) on 20 Oct 2026: 20 calls planned and recorded, all parsed with valid citations; the stub scored 8 PASS and 2 FAIL per version, as expected for its canned reply.
- Ran the live trial and the partial run myself with `--live` on 16 Oct 2026.
- Read the `context_builder.py` and `credential_scan.py` diffs (`git show 9f6d94c`, `git show 8e6eeca`, and `git diff main` for the Week 8 fixes) on 20 Oct 2026.
- Read the 16 flagger rules and their stated reasons (IO-1 to IO-5, AI-1 to AI-5, RM-1, RM-2, TB-1, TB-2, HC-1, HM-1) on 20 Oct 2026.
- Read the call record for the injection case on 20 Oct 2026: the model returned `no_action` with high confidence, the comment was flagged (AI-1), and the rationale quotes the planted comment as its reason, so I agree it is a model error.
- Scanned every file changed since `main` for non-ASCII characters on 20 Oct 2026 (`git diff --name-only main | ForEach-Object { Select-String -Path $_ -Pattern '[^\x00-\x7F]' -Encoding UTF8 }`): no matches.
- Confirmed no API key appears in any run record or committed file: yes. Confirmed on 20th October 2026

**What I changed or would still change myself**

- `scripts/check_sensitive.py` was changed with its owner's agreement, so its password-in-URL and key-name patterns match the fixed copies in `credential_scan.py`.
- The AI's editing tools inserted invisible characters again: escapes written as `\u` sequences were turned into literal zero-width, bidirectional, variation selector and line separator characters. Claude Code converted them back to visible escapes and checked the files were plain ASCII.
- The API key was in a file attached to the Claude panel. I replaced the key.
- I would still add independent injection cases from Member 4, the missing v1.1 calls and the v1.3 repeats, and a decision on the narrow Week 2 expectations.

**Not AI-generated**

- The choice of model (Gemini 2.5 Flash, from the Model Selection Note) and running the live calls with my own key.
- Approving the change to `scripts/check_sensitive.py`, agreed with its owner, Selina.
- The team documents and code written by other members, which I read but did not write.

**Data sent to the AI**

- Claude Code had read and write access to the repository, so it saw the existing code, tests and documents.
- It did not read `.env`, and it did not print environment variables.

**Data sent to the model provider**

- Only the synthetic Week 2 case inputs and the prompt text were sent to Gemini.
- No personal or production data was sent.
- I checked Google's free-tier terms on whether prompts and responses are used for training. Only synthetic data was sent in any case.

**Evidence status**

- Run records: `evidence/test-runs/week8/real-model/20261016T145654Z_live/` (trial) and `20261016T152707Z_live/` (partial). Committed in f1280de.
- Full suite as run by Claude Code: 645 passed, 1 skipped, 619 subtests on 16 Oct 2026, and 669 passed, 1 skipped, 625 subtests on main, 20 Oct 2026.
- Smoke run record: `evidence/test-runs/week8/smoke/20261016_gemini_smoke_run.json` (model, prompt version, latency, token usage and the model's output; no key or request headers).
- Terminal output of the full suite from my own terminal (PowerShell), 20 Oct 2026: `678 passed, 1 skipped, 6 warnings in 79.62s (0:01:19)`. The 6 warnings are pytest collection warnings for the `TestProposal` and `TestOutcome` dataclasses, not failures.
- Screenshot: `evidence/screenshots/week8/tests_member3.png`.

**Known limitations**

- Flags are recorded for review (the loop's `injection_flagged` entry for the sensed context, through `flag_trace_entry`, and the planner's entry for history flags) but change nothing the model sees.
- The retrieval query is the task goal text. With the shipped contract goal (the prompt's ROLE text) retrieval finds nothing in the fixture corpus, so a real session needs a specific goal.
- Earlier tool output is guarded before the planner shows it, but the stricter prose credential rules may over-redact ordinary code in read_file output.
- A truncated model reply is reported as a malformed one.
- One live end-to-end run is recorded (`evidence/test-runs/week8/agent-session/live_session.json`): completed in 2 iterations with a grounded `propose_test`, and the history guard redacted one credential-shaped assignment in turn 1's tool output. One run only; the automated tests use stub model clients.
- Groundedness is citation validity only. Nothing checks that the cited text supports the claim.
- `record_proposal`, `record_run` and `render_for_prompt` have no real caller, so memory never reaches the model.
- The real-model results are single calls: no query, invented requirement paths, temperature fixed at 0.0, one run per case, and no v1.1 score for the security case.
- The flagger rules and their test cases were written by the same author.
- Branch commits 30c6bc8 to 8e6eeca do not run on their own.

---
