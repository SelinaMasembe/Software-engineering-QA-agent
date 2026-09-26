# Week 4 Member 5: Approval Gate and Authorization Evidence

## Ownership

Member 5 provides the human approval gate, persistent approval queue,
authorization checks, audit logging, CLI approval process, and failure tests.

## Controlled Actions

`run_tests` requires explicit approval before execution.

`draft_issue` creates a local draft only. It does not submit an issue or pull
request and remains reviewable by a human.

## Approval Guarantees

The gate:

- records every approval request;
- records the approver and decision time;
- rejects unauthorized approvers;
- blocks until approval, denial, or timeout;
- never auto-approves after timeout;
- fails closed when approval is unavailable;
- records approval and rejection events in an append-only audit log;
- prevents a decided request from being decided again.

## Test Execution Boundary

`run_tests` accepts only test node IDs present in the frozen manifest.

It does not accept arbitrary paths or shell commands. Commands execute with
`shell=False` from the configured sandbox root.

Unknown test node IDs are rejected before an approval request is created.

## Evidence Files

Primary implementation:

- `src/orchestrator/approval_gate.py`
- `src/tools/approval_tools.py`
- `scripts/approve_cli.py`
- `scripts/member5_approval_demo.py`
- `tests/integration/test_approval_gate.py`

The sanitized RAG fixture and provenance correction are also part of the
security evidence:

- `tests/fixtures/member2/corpus/logs/test_run_2026_09_15.txt`
- `src/rag/retrieval.py`
- `src/ingestion/tag_provenance.py`

## Automated Verification

Run the Member 5 integration tests:


Run the dispatcher contract tests:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.integration.test_tool_dispatcher -v
```
