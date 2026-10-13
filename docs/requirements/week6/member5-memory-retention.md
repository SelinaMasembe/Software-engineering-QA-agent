# Week 6 Member 5: Memory Retention and Human Memory Controls

Task (Task Allocation Plan, Member 5, Week 6): *"Write the scheduled job that
deletes memory records once they have passed their retention period."*
Deliverables: `src/memory/retention.py` and the Week 6 progress report.

At the team's request (Member 3's retention message), this week also adds the
two human memory controls that the retention decision depends on: a **clear
command** and the **rejection path**.

---

## 1. The basics

**What is the agent's memory?** Between sessions the agent remembers, for
each code module, which tests it *proposed*, which were *run*, and which a
human *rejected*. That stops it suggesting the same test again. Each of these
facts is one **memory record**, stored in a small database file,
`data/memory.sqlite3`.

**What is retention?** A retention rule answers "how long do we keep a
record, and how does it get deleted?" The course brief requires the team to
document what is stored, why, who can access it, **retention and deletion**.

**What is a scheduled job?** A program that runs automatically at set times,
for example every night at 2 a.m., without anyone pressing a button. On a Mac
or Linux machine this is usually done with `cron` or macOS `launchd`.

**Who built what:**

| Piece | Owner | File |
| --- | --- | --- |
| What a memory record contains | Member 1 | `src/memory/schema.py` |
| The database, including "list expired" and "delete safely" | Member 2 | `src/memory/store.py` |
| The memory API the agent uses, and when a record gets an expiry date | Member 3 | `src/memory/api.py` |
| Proof that memory can't bypass approval | Member 4 | `tests/test_memory_guard.py` |
| **Retention: the scheduled job, the clear command, the rejection path** | **Member 5** | `src/memory/retention.py`, `scripts/approve_cli.py` |

---

## 2. The retention decision

The team voted for **Option A: memory is kept until a human clears it.**

- **Why.** Memory exists to stop the agent repeating a proposal a developer
  already saw or declined. A rejection is final and is never updated again,
  so under a fixed period (e.g. 90 days) rejections would be the first
  records deleted, and declined tests would come back.
- **Consequences accepted.**
  - Records accumulate. Each module is capped at 1000 records, which is the
    signal for a human to review and clear.
  - `rejected_by` stores a **role or team handle** such as `qa-lead`, not a
    personal name or email, so no personal data is kept.
  - A human can clear a module's memory at any time, for example when the
    module is rewritten.

In code, the decision is one named setting in `src/memory/retention.py`:

```python
MEMORY_EXPIRES_AFTER: timedelta | None = None   # keep until a human clears it
```

Whoever creates the memory API passes it in:
`ProposalMemory(store, expires_after=MEMORY_EXPIRES_AFTER, clock=...)`.
If the team ever chooses a period, this one value changes (for example to
`timedelta(days=180)`) and the scheduled job starts enforcing it, with no
other code change.

---

## 3. What `src/memory/retention.py` does

### 3.1 The scheduled job: `purge_expired`

```text
every run:
  1. ask Member 2's store for records whose expiry date is now or earlier
  2. for each one, delete it only if it is unchanged since it was listed
  3. write one audit line per deletion and one summary line per run
```

- **It only deletes records whose expiry date has passed.** A record with no
  expiry date is never touched. Under Option A no record has one, so **the job
  deletes nothing, on purpose**. There is deliberately no "backstop" that
  removes records without an expiry: that would quietly turn Option A into a
  fixed period.
- **Safe deletion.** Every record has a revision number that goes up each
  time it changes. The job deletes with `expected_revision`, so if a record
  changed after it was listed (for example a proposal was just run and got a
  fresh expiry), it is **skipped, not deleted**.
- **Bounded.** It works in batches of 100 and stops after 10,000 deletions in
  one run, so a huge backlog can't lock the database for long.
- **Dry run.** `--dry-run` shows what would be deleted without deleting.
- **Scheduling.** `run_scheduled` repeats the job on an interval and opens a
  fresh database connection for each run. If one run fails, the failure is
  audited and the next run tries again.

### 3.2 The human clear command: `clear_module`

Deletes all memory records for **one module**, only when a person asks:

- `--by` must be a role or team handle (letters, digits, `.`, `-`, `_`), and
  must be listed in `QA_AGENT_APPROVERS`. Email addresses and names with
  spaces are refused.
- `--reason` is required and goes to the audit log.
- **Preview first.** Without `--confirm` it only lists what would be deleted.
- Each deletion is revision-checked, like the scheduled job.

### 3.3 The audit log

Every run, preview, refusal and deletion is appended to
`data/memory_audit.jsonl`, one JSON object per line. It holds identifiers
only: namespace, record ID, revision, who, and why. It never holds a test
title or other stored text. The file is ignored by Git.

### 3.4 The agent can never call it

`src/agent/` (the agent loop) and `src/tools/` (the tools the AI can request)
must never import `memory.retention`. A test reads every file in those
folders and fails if one does. This mirrors the boundary Member 3 put around
`record_rejection`.

---

## 4. The rejection path (`scripts/approve_cli.py`)

Member 3's `ProposalMemory.record_rejection` had no caller. A human now
records a rejection with the same approval CLI used for tool approvals:

```bash
export QA_AGENT_APPROVERS="qa-lead,team-j"

# 1. see what the agent remembers for a module, and each proposal's key
PYTHONPATH=src python3 scripts/approve_cli.py proposals src/auth/login.py

# 2. reject one
PYTHONPATH=src python3 scripts/approve_cli.py reject-proposal src/auth/login.py PROPOSAL_KEY \
    --by qa-lead --reason "duplicates an existing test"
```

- `--by` must be an authorized role handle; an unauthorized one is refused
  and audited, and nothing changes.
- The reason goes to the approval audit log (`data/audit.log`), because the
  memory record has no free-text field.
- It lives in `scripts/`, outside `src/agent` and `src/tools`, so the agent
  cannot reach it.

---

## 5. How to run and schedule it

```bash
# run the expiry job once (what a schedule calls)
PYTHONPATH=src python3 -m memory.retention run
PYTHONPATH=src python3 -m memory.retention run --dry-run

# keep it running in this terminal, once a day (Ctrl+C to stop)
PYTHONPATH=src python3 -m memory.retention schedule --every 86400

# human clear: preview, then confirm
export QA_AGENT_APPROVERS="qa-lead"
PYTHONPATH=src python3 -m memory.retention clear-module src/auth/login.py --by qa-lead --reason "module rewritten"
PYTHONPATH=src python3 -m memory.retention clear-module src/auth/login.py --by qa-lead --reason "module rewritten" --confirm
```

If there is no memory database yet, `run` and `clear-module` print "nothing to
do" and do **not** create one.

**Run it every night with cron** (macOS/Linux). Open the schedule with
`crontab -e` and add one line, replacing the path with your repository:

```text
0 2 * * * cd "/path/to/Software-engineering-QA-agent" && PYTHONPATH=src .venv/bin/python -m memory.retention run >> data/retention-cron.out 2>&1
```

`0 2 * * *` means "at minute 0 of hour 2, every day". On macOS, `launchd`
with a `StartCalendarInterval` of `Hour 2` is the native equivalent.

| Setting | Default | Purpose |
| --- | --- | --- |
| `QA_AGENT_MEMORY_PATH` | `data/memory.sqlite3` | Memory database |
| `QA_AGENT_MEMORY_AUDIT_PATH` | `data/memory_audit.jsonl` | Retention audit log |
| `QA_AGENT_APPROVERS` | none (required for clear and reject) | Role handles allowed to clear or reject |

---

## 6. Data handling summary (for the Memory Design and Data Handling Note)

| Question | Answer |
| --- | --- |
| What is stored | Per module: proposed, run and human-rejected test proposals (Member 1's schema). No diagnoses, logs, test output or source code. |
| Why | So the agent never repeats a proposal a developer already saw or declined. |
| Who can read | The agent's context, through Member 3's API; humans through `approve_cli.py proposals`. |
| Who can change | The agent records proposals and runs. Only a human records a rejection (`reject-proposal`) or deletes (`clear-module`). |
| Retention | Kept until a human clears it (Option A, `MEMORY_EXPIRES_AFTER = None`). |
| Deletion | Human clear command per module; the scheduled job deletes any record whose expiry has passed (none under Option A). Both are revision-safe and audited. |
| Personal data | `rejected_by` holds a role handle; email addresses are refused. |

---

## 7. Evidence and verification

- `src/memory/retention.py`
- `scripts/approve_cli.py` (`proposals`, `reject-proposal`)
- `scripts/member5_retention_demo.py`
- `tests/test_memory_retention.py` (32 tests)

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_memory_retention.py
PYTHONPATH=src python3 scripts/member5_retention_demo.py
python3 -m pytest -q
```

## 8. Known limits

- Under Option A the scheduled job deletes nothing. That is intended, but it
  means memory only shrinks when a human clears it.
- The clear command works on one module (up to 1000 records) at a time.
- `QA_AGENT_APPROVERS` is a shared list; the CLI trusts the `--by` value it is
  given, as the approval CLI already does. Real authentication would come
  from a deployment adapter.
- Expired records (if a period is ever set) stay visible to reads until the
  next job run, because Member 3's API does not hide them.
