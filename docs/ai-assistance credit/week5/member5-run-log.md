# AI-Assisted Engineering Record — Week 5 Member 5

- **Date:** 1–2 October 2026

- **Deliverable:**  
  Run logger that saves a log of every agent-loop run to
  `evidence/traces/runs/`, with a run index, unit and integration tests, a
  three-trace demonstration script, a run viewer, and Week 5 documentation.

  Evidence:
  - `evidence/traces/runs/`: three saved runs plus `index.jsonl`
  - `evidence/screenshots/week5/memeber5_tests.png`: test results

- **What I asked the AI for:**  
  I asked Claude Code to inspect the repository, the Week 5 assignment
  requirements and Member 2's unmerged agent-loop branch, and to implement
  code that saves a log of every run to the evidence folder. I asked it not
  to open the local `.env` file and to use `.env.example` only.

- **What the AI produced:**  
  The AI identified that Member 2's `AgentLoop` already defines a
  `TraceSink` protocol and leaves formatting and storage to Member 5, and
  implemented `RunLogger` against that protocol in
  `src/observability/run_logger.py`. It writes one JSON Lines file per run
  plus an append-only `index.jsonl`, keeps a paused-and-resumed run in one
  file, fsyncs each line, raises on write failure so the loop fails closed,
  redacts credential-like strings, and sanitizes session IDs used in file
  names. It used `.jsonl` rather than `.log` because
  `scripts/check_sensitive.py` blocks `*.log`.

  It also wrote `tests/test_run_logger.py` (18 unit tests),
  `tests/integration/test_run_logger_agent_loop.py` (7 tests against the
  real loop, including a pause, approve and resume with the real approval
  gate), `scripts/member5_run_log_demo.py` (three traces: completed,
  failure/recovery, approval pause and resume), `scripts/show_run_log.py`, and
  `docs/requirements/week5/member5-run-log.md`.

  In a follow-up on 2 October 2026 the AI also improved the Week 4 approval
  gate (non-blocking decisions, single-use approvals, self-approval and
  cross-process protection, human trace entries), switched Member 5's gate,
  demos and tests to Member 3's tools and removed the duplicate
  `approval_tools.py`, renamed the pre-commit hook so Git actually runs it,
  removed the re-added `.log` fixture and its scanner exemption, added
  `pytest.ini`, fixed stale paths, and rewrote the README.

- **Verification performed during the session:**  
  After the follow-up changes, the full suite (`python -m pytest -q`) gave
  289 passed with no failures. Before them it had two collection errors and
  a `4 != 3` RAG manifest failure. The 18 approval-gate tests and the 25
  run-logger tests passed. Both demos ran, and the run-log demo's approval
  trace showed `loop_paused`, a human `approval_granted` entry and
  `loop_halted`. `check_sensitive.py --all` exited 0, and
  `git hook run pre-commit` blocked a staged `.log` file, which confirms the
  renamed hook now runs.

- **Verification I performed myself (2 October 2026):**

  *Tests.* I ran these in my own terminal; the results are in
  `evidence/screenshots/week5/memeber5_tests.png`:

  | Command | Result |
  | --- | --- |
  | `python -m pytest -q` | 289 passed, 1 warning, 188 subtests passed |
  | `PYTHONPATH=src python -m unittest tests.test_run_logger tests.integration.test_run_logger_agent_loop -v` | Ran 25 tests, OK |
  | `PYTHONPATH=src python -m unittest tests.integration.test_approval_gate -v` | Ran 18 tests, OK |

  The one pytest warning is about `TestOutcome` in `src/models/types.py`
  being mistaken for a test class. It is not a failure.

  *Demos.*
  - `PYTHONPATH=src python scripts/member5_run_log_demo.py` saved three
    runs to `evidence/traces/runs/`:
    - `grounded-proposal` completed after 2 iterations (7 entries).
    - `failure-recovery` completed after 3 iterations (10 entries). A
      fabricated citation was rejected, then an invalid `run_tests` request
      was refused with `invalid_arguments`, then the agent recovered with a
      grounded proposal.
    - `approval-pause-resume` halted on `iteration_cap` after 3 iterations
      (14 entries). It paused for approval, resumed, recorded
      `approval_granted` by Alice as `actor=human`, and then ran the test.
  - `PYTHONPATH=src python scripts/show_run_log.py` listed the three runs
    with their outcomes. `--last` printed the approval run as a timeline.
  - `PYTHONPATH=src python scripts/member5_approval_demo.py` showed the gate
    returning `awaiting_approval`, then `executed` after Alice approved (the
    sandbox test passed), then `awaiting_approval` again for the identical
    request, because the approval had been used. The audit log recorded
    `approval_requested`, `decision_recorded`, `approval_consumed`, and then
    a new `approval_requested`.

  *Trace review.* I opened `evidence/traces/runs/` and confirmed that:
  - there are three run files (`grounded-proposal`, `failure-recovery`,
    `approval-pause-resume`) plus `index.jsonl`;
  - `failure-recovery` has a `citations_rejected` line followed later by
    `loop_completed`;
  - `approval-pause-resume` runs `loop_paused` → `loop_resumed` →
    `approval_granted` (`"actor": "human"`) → `tool_dispatched` →
    `loop_halted`;
  - `index.jsonl` has one row per run with its outcome (`loop_completed` or
    `loop_halted`);
  - searching the folder for `AIza`, `sk-`, `password` and my API key's
    first characters found nothing;
  - tool entries record argument names only (e.g.
    `"argument_keys": ["path"]`), not file contents or test output.

  *Code review.* I read:
  - `RunLogger.record()`: each step is saved immediately, and a failed write
    raises an error, which stops the agent;
  - `_SECRET_PATTERNS`: the credential patterns that are redacted before
    saving;
  - the lifecycle description at the top of
    `src/orchestrator/approval_gate.py`;
  - `decide()`: it refuses unauthorized approvers and self-approval;
  - the test names in `tests/test_run_logger.py`, checked against the
    behaviour each one claims to prove.

- **What I changed or rejected:**
  - When the AI found that `tests/fixtures/member2/corpus/logs/test_run_2026_09_15.log`
    had been re-added with a `.sensitive-scan-ignore` exemption, I decided
    to remove both rather than keep the exemption, because it undermined the
    sensitive-data check.
  - When the AI found that `run_tests` and `draft_issue` belong to
    Member 3, I chose to delete my own duplicate `src/tools/approval_tools.py`
    and use Member 3's tools, rather than delete Member 3's.
  - I chose not to edit the already-submitted Week 3 and Week 4 report
    `.docx` files, even though they contain the old `src/orchestration/`
    path.
  - I instructed the AI not to open `.env` and to use only `.env.example`.
  - After reviewing the code, tests and traces, I accepted the
    implementation without further code changes.

- **Sensitive data:**  
  No credentials, tokens, private keys or personal data were supplied. The
  local `.env` file was not opened.

Responsibility for the submitted design, code, tests, documentation and
cited verification results remains with Member 5.
