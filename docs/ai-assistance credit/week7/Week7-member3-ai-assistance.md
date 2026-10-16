## Week 7 AI assistance: Member 3 (AI Engineering Lead)

**Date:** 16th Oct 2026

**Deliverable:** AI-behaviour evaluation criteria, adversarial cases (`tests/adversarial/fixtures.py`), scorer (`src/evaluation/scorer.py`), evidence wrapper fix in `src/rag/context_builder.py`, and injection flagging (`src/rag/injection_flagging.py`).

**What I asked the AI for**

- Claude (claude.ai): turning the Week 7 row of the allocation plan and the brief into read-only exploration prompts, reviewing the exploration reports, designing the evaluation criteria and the case categories, deciding where the guardrail work should sit, and writing the evaluation criteria document and this log.
- Claude Code: re-exploring the repository before each step, building the scorer, the adversarial cases and their tests, fixing the evidence wrapper, and building the injection flagger.

**What the AI produced**

- A draft of the evaluation criteria, which I reviewed and kept as the team document.
- `src/evaluation/scorer.py`, 24 then 26 cases, and their tests.
- The wrapper fix in `context_builder.py` and its regression tests.
- `src/rag/injection_flagging.py` with 11 rules, and its tests.
- The wording of the scripted planner responses in the cases.

The cases and the flagger rules were written in the same project by the same author. Passing them shows the rules match my fixture wording, not that the flagger detects injections in general.

**Verification I performed myself**

[CONFIRM EACH ITEM YES OR NO, WITH THE DATE, BEFORE SUBMITTING. DELETE ANY LINE I DID NOT DO.]

- Ran the full suite in my own terminal: 607 passed, 1 skipped, 6 warnings, 539 subtests passed in 67.46s (0:01:07).
- Read the `context_builder.py` diff line by line.
- Scanned changed files for hidden Unicode characters: 15 | files with hidden or non-ASCII characters: 0.
- Checked each case's user story and risk against the register: files scanned: 15 | files with hidden or non-ASCII characters: 0.
- Read the 11 flagger rules and judged them against real requirement wording: CONFIRMED.
- Confirmed the case counts and outcome counts against the run output: 22 passed, 1 warning, 178 subtests passed in 3.90s
cases: 30
{'PASS': 29, 'PARTIAL': 1, 'FAIL': 0}
['ADV-INC-03'].

**What I changed or would still change myself**

- I approved changing `context_builder.py` to neutralise the evidence tag breakout, instead of only flagging it, because flagging leaves the forged text in front of the model.
- I rejected recording a flag as a `BoundaryViolationAttempt` with `declined=True`, because a flag does not mean an action was requested and declined. The scorer carries `context_flags` instead.
- I required the failing evidence to be saved before each fix, so the before and after results exist.
- The AI's editing tool inserted invisible characters (zero-width, bidirectional control and line separator characters) into four source files while writing escapes. They were converted back to visible escapes, and I checked for others.
- I would still add independent injection cases from Member 4, a real model run, and a check that cited text supports the claim, which is not built.

**Not AI-generated**

- The decision to take ownership of injection flagging, because the allocation plan had no owner for it.
- The decision to fix the wrapper in my own Week 3 file.
- The decision to score known gaps as PARTIAL, and the decision that safety violations are a hard gate.
- The team documents and code written by other members, which I read but did not write.
- The standing decisions in the credit log's earlier entries.

**Data sent to the AI**

Repository code and reports, the Security and Risk Register, the AI Boundary Matrix, the Acceptance Criteria Review, the allocation plan, and the assignment brief. All fixtures are synthetic. No credentials were sent. 
**Evidence status**

- Terminal output of the full suite: 607 passed, 1 skipped, 6 warnings, 539 subtests passed in 67.46s (0:01:07).
- Screenshot of the green run saved to `evidence/screenshots/week7/`: saved
- All results in this entry are scripted. No real model run is recorded for Week 7.

---