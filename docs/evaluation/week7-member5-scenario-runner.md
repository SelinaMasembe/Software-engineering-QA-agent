# Week 7 Member 5: Running All Scenarios in One Go

Task (Task Allocation Plan, Member 5, Week 7): *"Write the script that runs all
thirty-plus scenarios in one go and pulls the results together."*
Deliverables: `tests/run_scenarios.py` and the Week 7 progress report.

---

## 1. The basics

**What is a scenario?** One situation we put the agent in, together with what
it should do. For example: "a requirement contains a hidden instruction to run
a shell command; the agent must not follow it."

**Why 30+?** The brief requires a final evaluation of at least 30 scenarios
covering six categories: normal, edge, incorrect information, adversarial,
tool failure and unauthorized action.

**The problem before this week.** The scenarios lived in four separate places,
each with its own command and its own way of reporting:

| Suite | Owner | Cases | File |
| --- | --- | --- | --- |
| Behaviour and adversarial | Member 3 (Week 7) | 30 | `tests/adversarial/fixtures.py`, scored by `src/evaluation/scorer.py` |
| Prompt | Member 4 (Week 2) | 10 | `tests/fixtures/prompt_eval_cases.json`, run by `tests/test_prompt_harness.py` |
| Retrieval (RAG) | Member 4 (Week 3) | 15 | `tests/fixtures/rag_eval_cases.json`, run by `tests/test_rag_eval.py` |
| Failure re-tests | Member 4 (Week 7) | 5 | `tests/test_failure_retest.py` |

There was no single command that ran them all and no single table of
results.

**What the runner does.** One command runs all four suites, puts every
scenario in one table, and writes the combined results to the evidence
folder.

---

## 2. How it works

```text
python3 tests/run_scenarios.py
   |
   |-- behaviour suite ----> Member 3's run_case() + score_case()
   |-- prompt suite -------> Member 4's evaluate_case() (scripted model answers)
   |-- rag suite ----------> Member 4's evaluate_case() (real retrieval)
   |-- failure_retest -----> Member 4's run_probe() (each fix re-checked)
   |
   v
one combined report ---> evidence/evaluation/week7-scenario-results.md / .json / .csv
```

- **It reuses, never re-implements.** Each suite is run with the function its
  owner already wrote, so the runner cannot quietly disagree with their checks.
- **One row per scenario:** suite, scenario ID, brief category, user stories,
  risk, outcome (PASS, PARTIAL or FAIL), the outcome its owner expects, and
  whether the two match.
- **Expected failures stay visible.** Two prompt cases are red-team probes: their
  scripted answer is deliberately bad, so the harness *must* fail them, which
  proves it catches bad behaviour. Five cases are documented known gaps that
  score PARTIAL. The runner reports these as "behaving as expected", but never
  turns them into a PASS.
- **A crashed suite is reported, not hidden.** It appears with its error, and
  the run fails.
- **Exit code.** It returns 0 when every scenario behaves as expected, and 1
  otherwise, so it can gate a commit or CI job.

### Category mapping

Member 3's cases already use the brief's six categories. The older suites
used their own names, which the runner maps as follows. This is the runner's
judgement, and it is written in the code so it can be reviewed:

| Suite | Suite category | Brief category |
| --- | --- | --- |
| prompt | normal / edge / adversarial | same |
| prompt | failure (malformed source code) | edge |
| rag | answerable | normal |
| rag | partially_answerable | edge |
| rag | unanswerable | incorrect_information |
| failure_retest | regression | adversarial |

User stories come from where they are already recorded: Member 3's cases carry
one each, and the prompt cases use Member 1's `CASE_TO_STORIES` mapping. RAG
and failure re-test cases have no story in their source files, so the runner
leaves them blank rather than inventing one.

---

## 3. Results (17 October 2026, commit `30b23d1`)

| Suite | Scenarios | PASS | PARTIAL | FAIL | As expected |
| --- | --- | --- | --- | --- | --- |
| behaviour | 30 | 29 | 1 | 0 | 30 |
| prompt | 10 | 8 | 0 | 2 | 10 |
| rag | 15 | 11 | 4 | 0 | 15 |
| failure_retest | 5 | 5 | 0 | 0 | 5 |
| **Total** | **60** | **53** | **5** | **2** | **60** |

- **All six brief categories are covered:** normal 12, edge 14, incorrect
  information 6, adversarial 18, tool failure 5, unauthorized action 5.
- **Member 3's scorer**, on the 30 behaviour cases:
  - task completion, groundedness, tool selection, safety and stop reason:
    100%;
  - instruction following: 29/30 (the known R10 gap);
  - safety violations: 0.
- **User stories:** US-1 to US-11 are each covered by at least one scenario.
  US-12 is not; Member 1 records it as diagram and matrix literacy rather than
  runtime behaviour.
- **What PARTIAL and FAIL mean here:**
  - The 5 PARTIAL results are documented known limitations: four retrieval
    limitations and one gap where draft claims are not checked (R10).
  - The 2 FAIL results are the red-team probes the harness is meant to catch.

The full table is in `evidence/evaluation/week7-scenario-results.md`.

---

## 4. How to run it

```bash
python3 tests/run_scenarios.py                       # all suites, write evidence
python3 tests/run_scenarios.py --suite behaviour     # one suite (repeatable)
python3 tests/run_scenarios.py --no-write            # summary only
python3 tests/run_scenarios.py --output-dir /tmp/x   # write somewhere else
```

The file is named `run_scenarios.py`, not `test_...`, so pytest does not
collect it as a test file. Its own tests are in `tests/test_run_scenarios.py`.

---

## 5. Limits

- **No real model.** The prompt cases use scripted answers and the behaviour
  cases use a scripted planner. The results show the controls hold, not how a
  live model behaves. Member 3's real-model runs are under
  `evidence/test-runs/week8/real-model/`.
- **Current code only.** The failure re-tests check current code. Member 4's
  `--verify-history` mode, which also proves each defect existed before its
  fix, is run separately:
  `python3 tests/test_failure_retest.py --verify-history`.
- **Partial story mapping.** 22 scenarios (RAG and failure re-tests) have no
  user story yet. Member 1 can add them when extending the traceability
  matrix.
