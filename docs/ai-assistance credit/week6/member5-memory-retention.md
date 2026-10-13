# AI-Assisted Engineering Record — Week 6 Member 5

- **Date:** 9 October 2026

- **Deliverable:**  
  `src/memory/retention.py`: the scheduled job that deletes memory records
  once they pass their retention period, plus the human clear command.
  Following the team's retention vote and Member 3's request, I also added
  the human rejection path in `scripts/approve_cli.py`. Supporting files:
  - `tests/test_memory_retention.py`
  - `scripts/member5_retention_demo.py`
  - `docs/requirements/week6/member5-memory-retention.md`
  - README and `.gitignore` updates

- **AI tools used:**  
  Claude Code (Claude Opus 5.5), with read and write access to the
  repository, for exploration, implementation, tests and documentation.

- **What I asked the AI for:**  
  I asked Claude Code to:
  - recall my Week 6 task;
  - read the Week 6 brief and my teammates' merged memory code (`schema.py`,
    `store.py`, `api.py`, `mcp_interface.py`, `test_memory_guard.py`);
  - advise on the retention period before writing code.

  After the team vote, I asked it to implement everything required of
  Member 5 this week. I told it not to open `.env`, and asked it to explain
  everything for a beginner.

- **What the AI produced:**
  - **Advice.** It first recommended a fixed 90-day period, then changed its
    recommendation to Option A (keep until a human clears it) after
    checking Member 3's argument against `api.py`. Rejections are final and
    never re-stamped, so a fixed period would delete them first.
  - **`retention.py`:**
    - `MEMORY_EXPIRES_AFTER = None`, the decision recorded in code;
    - `purge_expired`, which deletes only records whose `expires_at` has
      passed, with no backstop for records without an expiry, as Member 3
      asked;
    - revision-checked deletes, batching, a per-run limit and a dry run;
    - `run_scheduled`, which opens a fresh connection per run and audits
      failed runs;
    - `clear_module`, the human command: role handle, authorization, reason
      and preview-then-confirm;
    - a JSON Lines audit with identifiers only, and a command line
      (`python -m memory.retention run | schedule | clear-module`).
  - **`approve_cli.py`:** `proposals` and `reject-proposal`, calling
    Member 3's `record_rejection` with an authorized role handle and
    auditing the reason.
  - **Tests:** 32 tests. They cover Option A deleting nothing, expiry-only
    deletion, skipping records that changed, batches and limits, the
    schedule, the clear command's safety checks, an import boundary keeping
    `src/agent` and `src/tools` away from retention, and the CLI rejection
    path.

- **Verification performed during the session:**  
  - The 32 retention tests passed.
  - The full suite (`python -m pytest -q`) gave 446 passed, 0 failed.
  - `check_sensitive.py --all` exited 0.
  - The demo showed:
    - nothing deleted under Option A;
    - only the expired record deleted when a 30-day period was simulated;
    - a rejection recorded under `qa-lead`;
    - a module cleared after a preview;
    - an audit log with no test titles.
  - The tests left the real `data/` folder empty.

- **Verification I performed myself (9–10 October 2026):**

  I ran these in my own terminal. The results are in
  `evidence/screenshots/week6/member5_evidence.png`.

  | Command | Result |
  | --- | --- |
  | `python -m pytest -q tests/test_memory_retention.py` | 32 passed, 1 warning, 9 subtests passed |
  | `python -m pytest -q` | 446 passed, 5 warnings, 276 subtests passed |
  | `PYTHONPATH=src python scripts/member5_retention_demo.py` | All four scenarios behaved as expected (below) |

  The warnings are pytest mistaking `TestProposal` and `TestOutcome` in
  `src/models/types.py` for test classes. They are not failures.

  What the demo showed:
  - **Option A:** the job run "10 years later" deleted 0 records, and
    `src/auth/login.py` still held its 2 records.
  - **A simulated 30-day period:** on day 31 the job deleted only the
    expired `src/billing/discounts.py` record and left `src/auth/login.py`
    untouched.
  - **A human rejection** was recorded as `rejected_by_human by qa-lead`.
  - **Clearing a module:** the preview said "would delete 2" and deleted
    nothing; after confirming, both records were deleted.
  - **The audit log** contained identifiers, counts and reasons only, and
    no test titles.

  I reviewed `retention.py` against the team's retention decision and
  checked these points:
  - `MEMORY_EXPIRES_AFTER` is `None` (keep until a human clears it).
  - The job only deletes records whose expiry has passed.
  - There is no code that deletes records without an expiry.
  - The clear command needs an authorized role handle, a reason and
    `--confirm`.
  - The agent cannot import it.

- **What I changed or rejected:**
  - I took the retention question to the team before any deletion code was
    written, because the brief requires us to state and justify a
    retention period. The team voted for Option A, keep until a human clears
    it, and I built to that decision.
  - I rejected the AI's earlier recommendation of a fixed 90-day period, and
    its suggested "backstop" that would delete records with no expiry. The
    backstop would quietly turn Option A into a fixed period, which Member 3
    also warned against.
  - I asked for the human clear command and the proposal-rejection path to
    be included this week. Both options needed them, and Member 3's design
    note assigned them to me.
  - I asked for a role or team handle (for example `qa-lead`) to be stored
    instead of a person's name, so memory holds no personal data.
  - I asked the AI not to open `.env`.
  - After my review, the tests and the demo, I accepted the implementation
    without further code changes.

- **Follow-up edits to teammates' files (10 October 2026):**  
  After I told the other members about these changes and they agreed, the
  AI made these small, wording-only edits:
  - **Member 1, charter Scope item (v):** added the retention line.
  - **Member 4, quality and security documentation:** added risk R14
    ("memory silently influencing a critical decision") to the Security and
    Risk Register, and marked the retention open item as resolved.
  - **Architecture diagram source:** step 12 no longer says diagnoses enter
    memory.
  - **Member 2, `src/memory/__init__.py`:** merged the doubled docstring.

  The AI also mistakenly ran `tag_provenance.py --verify`, which rewrote
  the knowledge corpus. It noticed, and restored those files from Git
  unchanged. Regenerating the corpus stays with Member 1.

- **Not AI-generated:**  
  The retention decision, which was made by team vote. The memory schema
  (Member 1), the store and MCP interface (Member 2), the memory API and
  design note (Member 3), and the guard tests (Member 4) were read but not
  edited.

- **Sensitive data:**  
  No credentials, tokens, private keys or personal data were supplied. The
  local `.env` file was not opened.

Responsibility for the submitted design, code, tests, documentation and
cited verification results remains with Member 5.
