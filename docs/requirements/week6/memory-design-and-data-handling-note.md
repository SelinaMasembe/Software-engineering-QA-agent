# Memory Design and Data Handling Note

BSE4104 Software-Engineering QA Agent | Member 3, AI Engineering | Week 6

*Updated 10 October 2026 after the team's retention vote and the Week 6
merges. The changes from Member 3's original draft are listed in section 10.*

## 1. Purpose and scope

This note records:
- what the QA Agent remembers between sessions;
- who is allowed to change that memory;
- how the memory is protected;
- how long it is kept, and how it is deleted.

It describes the implementation in `src/memory/api.py`, which sits on the
record shape in `src/memory/schema.py` and the SQLite store in
`src/memory/store.py`. Retention and deletion are implemented in
`src/memory/retention.py`.

**Adopted scope.** For each repository module, the agent remembers which tests
it proposed, which of those were run, and which a human explicitly rejected.
This stops it repeating a proposal a developer has already seen or declined.
The agent does not store or reuse past diagnoses.

**Memory is advisory context.** It can inform what the agent proposes. It can
never count as human approval, and it never authorises a tool call.

## 2. What is stored

Each record is a `ProposalMemoryRecord`, and only the fields below are stored.
The store holds them as an opaque JSON document, and every read passes the
document back through the schema before it is used.

| Field | Set when | Notes |
| --- | --- | --- |
| `module` | Proposal recorded | Normalised repository module name. It also forms the storage namespace, `proposal-memory:<module>`, so modules cannot mix. |
| `proposal_key` | Proposal recorded | Derived from module, title, requirement ID and target. Used as the record ID, which makes recording a proposal idempotent. |
| `title` | Proposal recorded | Short test title, capped at 300 characters. |
| `requirement_id`, `target` | Proposal recorded | Optional. They identify what the test covers. |
| `status` | Each transition | `proposed`, `run`, or `rejected_by_human`. Rejected is final. |
| `proposed_at`, `run_at`, `rejected_at` | Each transition | Timezone-aware timestamps from the injected clock. |
| `test_node_id` | Test run | Optional. The test that was executed. |
| `rejected_by` | Human rejection | Role or team handle of the person who rejected the proposal, for example `qa-lead`. The rejection path refuses email addresses and names with spaces. The handle is never shown to the model. |

### 2.1 What is never stored

- Diagnoses, root-cause explanations, or any conclusion about why a test failed.
- Test output, logs, stack traces, or source code.
- Model prompts or model responses.
- Credentials, tokens, or personal data. The rejector is recorded as a role
  handle, not a person.

The record type has no field that could hold these, and a test confirms that
stored documents contain only schema fields. This is the mechanism that keeps
the diagnosis-history design out of the system.

## 3. Who may write

| Operation | Intended caller | How it is controlled |
| --- | --- | --- |
| `record_proposal` | Agent orchestration, after a proposal is produced | Idempotent. If the proposal already exists, including a rejected one, the existing record is returned unchanged. |
| `record_run` | Agent orchestration, after an approved test runs | Only valid from `proposed`. Updates use the stored revision, so concurrent writers raise a conflict instead of overwriting. |
| `record_rejection` | The human approval path only: `scripts/approve_cli.py reject-proposal` | Requires an authorized role handle (listed in `QA_AGENT_APPROVERS`) and a reason, which is written to the approval audit log. Rejection is final. No module under `src/tools/` or `src/agent/` may import this function, and an automated test enforces that. |
| Clearing a module (`clear_module`) | A human only: `python -m memory.retention clear-module` | Requires an authorized role handle and a reason, previews first, and deletes only with `--confirm`. Each deletion is revision-checked and audited. `src/agent/` and `src/tools/` may not import `memory.retention`, and a test enforces that. |
| `find`, `list_for_module`, `render_for_prompt` | Any reader | Read only. Every document is validated on the way out. A corrupt document raises an error naming the record and returns no partial data. |

### 3.1 What is enforced and what is assumed

Two guarantees need to be stated carefully, because the code cannot prove them
alone.

- **Rejection and clearing are human-only.** The code checks that the handle
  is authorized and the reason is not blank. The import boundaries stop the
  agent loop and the tools from reaching either function. It cannot prove that
  the person at the command line is a human with that role: the CLI trusts the
  `--by` value it is given, as the tool-approval CLI already does. Real
  authentication would come from a deployment adapter.
- **Records come from schema-valid writes.** The store accepts any JSON. The
  schema check in `api.py` is what keeps unknown fields out, so nothing should
  call `MemoryStore.put` on a proposal namespace directly.

## 4. Reading memory into the prompt

Memory is rendered into the propose_action prompt by `render_for_prompt`.
Titles written by the agent in one session become input in a later session,
so stored text is a route for prompt injection. The renderer therefore treats
it strictly as data:

- Output is wrapped in a memory block that names the module. Angle brackets in
  titles are escaped, and every newline or control character is flattened to a
  space, so a stored title cannot close the block, open a new tag, or forge an
  extra entry line.
- The block is bounded by a record limit and a character limit. Whole lines
  are dropped to fit, and the opening tag reports how many records are shown
  out of how many exist.
- Order is deterministic: rejected first, then run, then proposed, newest
  first within each group. Rejections come first because they are the
  strongest signal not to repeat a proposal.
- The rejector handle is left out of the rendered block.

The prompt wording that describes this input must say that memory is context
to read, not instructions to follow. Prompt version 1.2
(`docs/prompts/propose_action/v1.2.md`) does this, and says tests were
"explicitly rejected by a human". The Prompt Specification and the Member 3
deliverables document still use the older wording (section 8).

## 5. Storage and protection

- **Location.** Records live in a single SQLite file, with the default path
  `data/memory.sqlite3` (override with `QA_AGENT_MEMORY_PATH`). The file is
  created with owner-only permissions (0600). It and its `-journal`, `-wal`
  and `-shm` side files are listed in `.gitignore`.
- **Version control.** The repository secret scan blocks committed `*.sqlite3`
  and `*.db` files, so a memory database cannot reach version control by
  accident.
- **Known limit on Windows.** Owner-only file permissions are not applied on
  Windows. The permission test in `test_memory_store.py` is therefore skipped
  there. The protection is real on Linux and macOS and absent on Windows
  development machines. This is acceptable for a project that stores no
  sensitive content, and it is recorded here so that the skipped test is not
  mistaken for a passing control.
- **No isolation from the same user.** The store provides no isolation from
  other processes running as the same user. Memory is not a security boundary
  against a compromised local account.

## 6. Retention decision

**Decision (team vote, Week 6): records are kept until a human clears them.**
The memory layer sets no automatic expiry. In code this is one setting:
`MEMORY_EXPIRES_AFTER = None` in `src/memory/retention.py`. The memory API is
constructed with `expires_after=MEMORY_EXPIRES_AFTER`, so every record is
written with no expiry time. The decision is also recorded in the project
charter, Scope item (v).

### 6.1 Why

- **Expiry would undo the purpose.** Memory exists to stop the agent
  repeating a proposal a developer has seen or declined. When a record lapses,
  a declined test returns as if it were new and the developer has to reject it
  again.
- **Rejections would go first.** A rejection is final and is never rewritten,
  so under any fixed period it would be the first kind of record to lapse.
- **The data is low sensitivity:** module names, test titles, statuses,
  timestamps and a role handle. There is no diagnosis, log or source content,
  so the usual privacy argument for short retention is weak here.
- **People decide.** Keeping records until a person decides otherwise matches
  the project principle that people decide and the system does not silently
  forget. It also follows the retention recommendation in the Week 6 memory
  description audit.

### 6.2 Consequences the team accepts

- **Records accumulate.** A module holds at most 1000 records, because that is
  the most the store can list in one call. A new proposal beyond that limit
  raises an error. Nothing is evicted automatically, so the agent never forgets
  a proposal without a human choosing it.
- **Hitting the limit is a signal** for a human to review and clear old
  records for that module.
- **No personal data.** `rejected_by` holds a role or team handle, not a
  personal name or email address. The rejection path enforces this.

### 6.3 How deletion works

There are two deletion mechanisms, both in `src/memory/retention.py` and both
revision-checked: a record that changed after it was listed is skipped, not
deleted.

1. **Human clear command.** `python -m memory.retention clear-module MODULE
   --by HANDLE --reason "..."` lists what would be deleted. Adding `--confirm`
   deletes every record for that one module. It:
   - requires an authorized role handle and a reason;
   - writes one audit line per deletion, plus a summary, to
     `data/memory_audit.jsonl`;
   - is unreachable from `src/agent/` and `src/tools/`.

   This is the mechanism that makes "kept until a human clears it" work.
2. **Scheduled expiry job.** `python -m memory.retention run`, which can be
   scheduled daily with `cron` or `launchd`. It deletes only records whose
   `expires_at` has passed.
   - It never deletes a record that has no expiry, so under this decision it
     deletes nothing, by design.
   - There is deliberately no backstop for records without an expiry, because
     that would quietly turn this decision into a fixed period.

If the team later chooses a finite period instead, change
`MEMORY_EXPIRES_AFTER` to that period. Record the decision here, together
with the consequence that rejections lapse with it. The scheduled job then
enforces it without a redesign.

The audit log records identifiers only (namespace, record ID, revision, who
and why), never a test title or other stored text. It is ignored by Git.

## 7. Written ahead of a missing consumer

Some parts of the memory layer were built against the contract rather than
against a working caller. They are tested in isolation and should be
rechecked when their consumers land.

| Part | Consumer | Status | Owner |
| --- | --- | --- | --- |
| `record_rejection` | The human path that records a rejected test proposal: `scripts/approve_cli.py reject-proposal` | **Built (Week 6)** | Member 5 |
| Clearing records | Human clear command, `python -m memory.retention clear-module` | **Built (Week 6)** | Member 5 |
| `render_for_prompt` | A real context sensor that builds the agent's input. None exists in the repository yet. | Open | Whoever wires the sensor |
| `record_proposal`, `record_run` | Agent orchestration that records each proposal and each approved run. The agent loop does not call the memory API yet. | Open | Whoever wires memory into the loop |

## 8. Follow-up actions

| Action | Owner | Status |
| --- | --- | --- |
| Add `-journal`, `-wal` and `-shm` side files to `.gitignore` | Member 3 | Done |
| Issue prompt version 1.2 so memory wording says "rejected by a human" | Member 3 | Done (`docs/prompts/propose_action/v1.2.md`) |
| Align the Prompt Specification and the Member 3 deliverables document with the v1.2 memory wording | Member 3 | Open |
| Correct architecture diagram step 12, which said confirmed diagnoses enter memory | Architecture owner (Member 2) | Source fixed in the `.drawio` file; re-export the page image if one is used |
| Add a memory risk to the risk register, including memory silently influencing a critical decision | Member 4 | Done (R14) |
| Build the human clear operation and the rejection call path | Member 5 | Done |
| Skip the owner-only permission test on Windows | Store author / Member 3 | Done |
| Fix the doubled docstring in `memory/__init__.py` | Store author | Done |
| Record the retention decision in the project charter | Member 1 | Done (Scope item (v)) |
| Regenerate the knowledge corpus copies so they match the updated charter and documents | Member 1 | Open |

## 9. Verification

- **Memory API tests.** The memory API has its own test file, using a real
  store in a temporary directory and an injected clock. It covers:
  - idempotent proposals and module isolation;
  - status transitions, final rejection and blank-rejector rejection;
  - corrupt-document handling;
  - prompt rendering bounds, escaping and newline flattening;
  - schema-only storage;
  - the import boundary for rejection.
- **Retention tests.** `tests/test_memory_retention.py` (32 tests) covers:
  - nothing is deleted under this decision;
  - only expired records are deleted, and changed records are skipped;
  - the schedule;
  - the clear command's safety checks;
  - the import boundary for retention;
  - the rejection path through `approve_cli.py`.
- **Full suite at the time of writing.**
  - On Member 3's draft (Windows), 9 October 2026: `403 passed, 1 skipped`.
    The skip is the Windows permission test in section 5.
  - On macOS, 10 October 2026: `446 passed, 0 failed`.

## 10. Revision history

| Date | By | Change |
| --- | --- | --- |
| 9 Oct 2026 | Member 3 | Original draft. |
| 10 Oct 2026 | Member 5 (with AI assistance) | Updated after the team vote and the Week 6 merges. Retention marked as the team decision, linked to `MEMORY_EXPIRES_AFTER` and the charter. Section 6.3 now describes the built clear command and the expiry-only scheduled job. `rejected_by` changed to a role handle. Sections 3 and 3.1 now name the rejection path and clear command. Section 4 notes prompt v1.2 and newline flattening. Section 5 records the Windows skip and the `.gitignore` side files. Sections 7 and 8 statuses updated. Verification updated. The decision, reasoning and structure are Member 3's. |
