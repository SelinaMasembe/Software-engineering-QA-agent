# AI-Assisted Engineering Record — Week 8 Member 5

- **Date:** 23 October 2026
- **Task (Task Allocation Plan, Week 8):**Fix any infrastructure bugs, pull together the appendices, finish the
  ClickUp board and repo evidence, and put together the presentation.
  Deliverables: final report Sections 9 and 10; presentation deck; fixes
  across `src/config/`, `src/observability/` (the plan's `src/logging/`) and
  `scripts/`, as needed. I also asked for a full review and a plain-language
  guide to the system.
- **AI tools used:**Claude Code (Claude Opus 5.5), with read and write access to the
  repository, on branch `week8-member5-final-evidence`, created from `main`.
- **What I asked the AI for:**

  - To act as a senior software QA officer, review the whole repository
    against the brief, and fix the infrastructure bugs in my scope.
  - To produce the appendices, the evidence index, a ClickUp checklist,
    Sections 9–10 (Markdown and Word), the presentation deck, and an
    easy-to-understand System Guide.

  I told it not to open `.env`, and to make all changes on a new branch from
  `main`.
- **What the AI produced:**

  - **Review.** Three parallel read-only reviews: infrastructure, the
    end-to-end system, and an evidence inventory against every brief
    deliverable. Its findings, with severity and owner, are in
    `docs/final-report/qa-review.md`.
  - **Infrastructure fixes, each with a regression test:**
    - API key hidden from `ModelSettings`'s printed form;
    - finite, bounded timeout and token limits;
    - endpoint credential and whitespace checks, and blank settings falling
      back to their defaults;
    - the secret scanner failing (exit 2) on a missing file instead of
      passing it;
    - repository-rooted approval data paths;
    - run-log fixes: UTC file names, `QA_AGENT_TRACE_DIR` honoured, and
      counters advanced only after a write;
    - `show_run_log.py` that never writes and accepts listed names;
    - a `--trace-dir` option on `run_agent_session.py`.
  - **Hygiene:**
    - pinned `requirements.txt` and a corrected `.env.example`;
    - a GitHub Actions CI workflow;
    - `.DS_Store` files untracked;
    - the stale local `src/orchestration/` folder removed;
    - README and setup corrections.
  - **Documents:**
    - `docs/SYSTEM_GUIDE.md`;
    - `docs/final-report/appendices.md`, `clickup-checklist.md`,
      `qa-review.md` (an evidence index was also drafted; I removed it);
    - drafts of Sections 9–10, which at my request covered the whole
      project, not only Week 8: a project summary, what the group did week
      by week, what was built, and the challenges of all eight weeks with
      how each was resolved. The challenges come from the group's weekly
      progress reports and the Failure Catalogue. These drafts were merged
      into the final report and then removed.
    - The assembled final report, `final-engineering-report.md` and
      `Final_Engineering_Report_Group_J.docx`, built on my own edited
      version of the Sections 9–10 report (cover, links and wording kept). It covers
      every topic in the brief in Sections 1–10, is 12 pages in Word with the
      cover, and has Appendices A–G attached after the report. Sections 4–7
      (Member 3, not submitted) and Section 5 (no owner) were drafted from the
      code, the Model Selection Note, the Grounding Design Note and the
      weekly documents, and are marked for Member 3 to review.
  - **Deck.** `docs/presentation/QA_Agent_Final_Presentation-GroupJ.pptx`: 12
    slides following the brief's presentation structure, with speaker notes,
    native charts and tables. It passed the skill's file validator and an
    independent visual review; the defects that review found were fixed.
- **Verification performed during the session:**

  - **Full suite:** `python -m pytest -q` gave 739 passed (723 before, plus
    16 new regression tests).
  - **Scenarios:** `tests/run_scenarios.py` gave 61 scenarios, all as
    expected.
  - **Secret scan:** `check_sensitive.py --all` exited 0. The scanner fix
    was checked by hand: a missing file gives exit 2, and a relative path
    from a subfolder is scanned.
  - **Live-session option:** an offline agent session with `--trace-dir`
    saved a run log that `show_run_log.py` replays.
  - **Deck:** it passed the validator. Quick Look cannot draw native charts,
    so the chart on slide 7 should be checked in PowerPoint.
  - **No side effects:** the real `data/` and evidence files were not
    changed by the tests.
  - **Mistakes caught and corrected during the session:**
    - two new tests were initially wrong (a single-run index expectation,
      and a scanner test run outside a Git repository);
    - the first deck build failed because its sections were not declared
      first.
- **Verification I performed myself (23 October 2026):**

  I ran these in my own terminal on branch `week8-member5-final-evidence`.
  The results are in `evidence/screenshots/week8/tests_member5.png`.

  | Command                                      | Result                                                                                                                                                                                                             |
  | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
  | `python3 -m pytest -q`                     | 739 passed, 6 warnings, 637 subtests passed                                                                                                                                                                        |
  | `python3 tests/run_scenarios.py`           | 61 scenarios: PASS 54, PARTIAL 5, FAIL 2. Each suite was as expected (behaviour 30/30, prompt 10/10, rag 15/15, failure_retest 6/6). "Result: all scenarios behaved as expected"; the results files were rewritten |
  | `python3 scripts/check_sensitive.py --all` | No output, which means no secrets or personal data found                                                                                                                                                           |

  The 6 warnings are pytest mistaking `TestProposal` and `TestOutcome` in
  `src/models/types.py` for test classes (open item F in the QA review).
  They are not failures.
- **What I changed or rejected:**

  - I asked for the review to be done as a senior QA officer would, and for
    a plain-language System Guide in addition to the deliverables.
  - I required every change to be made on a new branch from `main`.
  - I accepted the implementation after running the checks above.
- **Sensitive data:**
  No credentials, tokens, private keys or personal data were supplied. The
  local `.env` file was not opened.

Responsibility for the submitted design, code, tests, documentation and
cited verification results remains with member 5.
