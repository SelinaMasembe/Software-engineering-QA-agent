# Week 4 Member 5: Approval Gate and Authorization Evidence

## Ownership

Member 5 provides the human approval gate, persistent approval queue,
authorization checks, audit logging, CLI approval process, and failure tests.

The approval-required tools themselves (`run_tests`, `draft_issue`) are
Member 3's (`src/tools/run_tests.py`, `src/tools/draft_issue.py`). The gate
works with any tool the dispatcher marks `REQUIRES_APPROVAL`.

> **Consolidation (2 October 2026).** Week 4 also shipped a stand-in
> `src/tools/approval_tools.py` with its own `RunTestsTool` and
> `DraftIssueTool`, written on a branch that did not yet contain Member 3's
> tools. It duplicated Member 3's work, so it was removed and the gate's tests
> and demos now use Member 3's tools, whose sandbox also strips environment
> variables and enforces a timeout.

## Controlled Actions

- `run_tests` requires explicit approval before execution and runs only
  pytest node IDs from a fixed manifest, through `src/sandbox/executor.py`.
- `draft_issue` also requires approval. It stores a local draft only and
  never submits an issue or pull request.

## Approval Guarantees

The gate (`src/orchestrator/approval_gate.py`):

- records every approval request, keyed by a fingerprint of the session,
  action and validated arguments;
- returns the current decision (`pending`, `approved`, `denied`) instead of
  blocking, so the agent loop can pause and resume; `wait_seconds` restores
  the blocking behaviour for demos;
- does not create a duplicate request while one is pending;
- delivers every decision exactly once: an approval is consumed when the
  tool runs and cannot be replayed;
- rejects unauthorized approvers without cancelling the request;
- rejects self-approval (the requester cannot approve their own request);
- expires undecided requests and never auto-approves;
- locks the queue file across processes, so the agent and the CLI cannot
  overwrite each other's changes;
- fails closed when the queue is missing, corrupt or approval is unavailable;
- records requests, decisions, consumption, expiry and blocks in an
  append-only audit log;
- optionally sends human decisions to the Week 5 run log as `actor=human`
  trace entries.

## Evidence Files

- `src/orchestrator/approval_gate.py`
- `scripts/approve_cli.py`
- `scripts/member5_approval_demo.py`
- `tests/integration/test_approval_gate.py`
- `docs/requirements/week4/member5-approval-gate-explained.md`

The sanitized RAG fixture and provenance correction are also part of the
security evidence:

- `tests/fixtures/member2/corpus/logs/test_run_2026_09_15.txt`
- `src/rag/retrieval.py`
- `src/ingestion/tag_provenance.py`

## Automated Verification

Run the Member 5 approval-gate tests:

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_approval_gate -v
```

Run the dispatcher contract tests:

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_router -v
```

Run the demonstration:

```bash
PYTHONPATH=src python3 scripts/member5_approval_demo.py
```
