# AI-Assisted Engineering Record — Week 7 Member 5

- **Date:** 17 October 2026

- **Deliverable:**  
  `tests/run_scenarios.py`, the script that runs all thirty-plus evaluation
  scenarios in one go and pulls the results together, and the Week 7 progress
  report. Supporting files:
  - `tests/test_run_scenarios.py`
  - the results in `evidence/evaluation/week7-scenario-results.{md,json,csv}`
  - `docs/evaluation/week7-member5-scenario-runner.md`
  - README updates
  - removal of three committed Word lock files, with a `.gitignore` rule

- **AI tools used:**  
  Claude Code (Claude Opus 5.5), with read and write access to the
  repository.

- **What I asked the AI for:**  
  I gave Claude Code the full Team Task Allocation Plan and the capstone
  brief, and asked it to:
  - remember them;
  - review the repository;
  - do my Week 7 task on the `week7-script-to-run-all-scenarios` branch;
  - explain everything for a beginner.

  I told it not to open `.env`.

- **What the AI produced:**
  - **What it found first.** It read the four scenario suites and found
    that the 30+ scenarios were spread across four files with four different
    runners, and that Member 1's traceability matrix covered only the 10
    prompt cases, because no combined list existed.
  - **`tests/run_scenarios.py`.** It runs each suite with its owner's own
    functions:
    - Member 3's `run_case` + `score_case`;
    - Member 4's prompt and RAG `evaluate_case`;
    - Member 4's `run_probe`.

    It then combines the 60 results into one report with:
    - totals per suite and per brief category;
    - Member 3's scorer criteria;
    - user-story coverage;
    - a list of anything unexpected.

    Expected failures (red-team probes) and known gaps are reported as
    behaving as expected, without being turned into PASS. A crashed suite
    fails the run. It writes Markdown, JSON and CSV evidence.
  - **`tests/test_run_scenarios.py`.** 16 tests: a real run of all suites,
    plus aggregation, exit-code and command-line checks.
  - **Docs.** The explainer, the README, the Week 7 report, and the
    lock-file cleanup.

- **Verification performed during the session:**
  - **Runner tests:** 16 passed under both pytest and unittest.
  - **Full suite:** `python -m pytest -q` gave 670 passed, 0 failed.
  - **Real run:** 60 scenarios (PASS 53, PARTIAL 5, FAIL 2), all 60
    behaving as their owners expect, exit code 0.
  - **Secret scan:** `check_sensitive.py --all` exited 0.

  The first test run showed a small bug in the AI's own code: the summary
  printer fixed its output stream when the program loaded, so the tests
  could not capture its output. It was fixed before acceptance.

- **Verification I performed myself (17 October 2026):**

  I ran these in my own terminal. The results are in
  `evidence/screenshots/week7/member5_wee7_evidence.png`.

  | Command | Result |
  | --- | --- |
  | `python3 tests/run_scenarios.py` | 60 scenarios: PASS 53, PARTIAL 5, FAIL 2. Each suite was as expected (behaviour 30/30, prompt 10/10, rag 15/15, failure_retest 5/5). "Result: all scenarios behaved as expected"; the JSON, Markdown and CSV files were written. |
  | `python -m pytest -q tests/test_run_scenarios.py` | 16 passed, 6 subtests passed |
  | `python -m pytest -q` | 670 passed, 6 warnings, 625 subtests passed |

  The warnings are pytest mistaking `TestProposal` and `TestOutcome` in
  `src/models/types.py` for test classes. They are not failures.

  I reviewed all the changes before accepting them:
  - the runner;
  - its tests;
  - the results files;
  - the explainer;
  - the README and `.gitignore` edits;
  - the Week 7 report.

  In the CSV results file (`evidence/evaluation/week7-scenario-results.csv`)
  I checked what each column means. Each row is one scenario. The
  `as_expected` column compares the actual `outcome` with the outcome its
  owner expects; filtering it for `False` gives no rows. The two FAIL rows
  are the prompt red-team probes, and their `reasons` show the harness
  caught the bad behaviour. The five PARTIAL rows are documented known
  limitations.

- **What I changed or rejected:**
  - I gave the AI the full Task Allocation Plan and brief first, so it worked
    from my real Week 7 task instead of guessing it.
  - I asked for clarification on the CSV results file before accepting it.
  - I agreed to removing the three Word lock files that had been committed,
    and to adding the `.gitignore` rule, as part of my DevOps role.
  - After reviewing the changes and running the tests myself, I accepted the
    implementation without further code changes.

- **Not AI-generated:**  
  The scenarios themselves and their checks: Member 3's cases and scorer,
  Member 4's prompt, RAG and re-test suites, and Member 1's story mapping.
  They were read and called, not edited.

- **Sensitive data:**  
  No credentials, tokens, private keys or personal data were supplied. The
  local `.env` file was not opened.

Responsibility for the submitted design, code, tests, documentation and
cited verification results remains with Member 5.
