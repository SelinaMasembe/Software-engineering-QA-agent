# Week 4 Member 2 Deliverable Guide: Tool Calling and Orchestration

## My Responsibility and Deliverables

In Week 4 I am responsible for the orchestration boundary that turns one model
proposal into one safe, structured result. I own how a tool request is parsed,
checked, routed, and reported. I do not own the tools or the approval decision.

My deliverables are:

- `ToolDispatcher`, which dispatches at most one tool request per call and
  blocks whenever a required check or dependency is missing.
- `ToolRegistry`, a fixed allow-list of tool implementations registered in
  code. The model cannot add or rename a tool.
- The public `Tool` and `ApprovalGate` protocols for Members 3 and 5.
- Stable, JSON-ready result statuses and reason codes.
- Sixteen offline tests for the dispatcher's safety boundaries.
- An offline demonstration that uses canned demo adapters.
- The L4 tool-calling architecture view.

This work does not implement the four real tools or the approval gate. The
dispatcher is ready to accept them through the contracts below.

## Owned and Excluded Work

| Work | Owner | How my code uses it |
| --- | --- | --- |
| Dispatcher, registry, result types, statuses and codes | Member 2 (me) | Implemented in `src/orchestration/`. |
| `ProposalSet`, `Action` and structural parsing | Member 1 | I call `ProposalSet.model_validate_json` rather than redefine the types. |
| Citation validation | Member 1 | The caller runs it before dispatch. |
| Four tools, their schemas and role metadata | Member 3 | Registered through the `Tool` protocol; my dispatcher enforces the declared roles. |
| Failure and authorization evidence suite | Member 4 | Can drive the dispatcher with the real tools. |
| Approval policy and human-approval gate | Member 5 | Injected through the `ApprovalGate` protocol. |
| Week 4 progress report | Member 5 | Receives my test, demo and architecture evidence. |

## Single-Turn Execution Flow

```text
Raw model response
        |
        v
ProposalSet parsing                              -> REJECTED / malformed_request
        |
        v
Tool action?                                     -> NOT_A_TOOL
        |
        v
Registered in ToolRegistry?                      -> REJECTED / unknown_tool
        |
        v
Caller role allowed?                             -> REJECTED / unauthorized
        |
        v
Tool.validate_arguments                          -> REJECTED / invalid_arguments
        |
        v
Approval required? -> ApprovalGate.check
        missing/unavailable/denied/pending        -> safe non-execution result
        |
        v
Tool.run, exactly once                           -> TOOL_ERROR / execution_failed
        |
        v
Tool.validate_output + strict JSON + size limit  -> TOOL_ERROR / invalid_output
        |
        v
DispatchResult: EXECUTED with validated output
```

Read-only tools do not consult the approval gate. The dispatcher deep-copies
arguments between trust boundaries. Exception text from tools and gates is not
copied into result messages, so secrets in error strings do not leak. Each call
dispatches one proposal and returns; it is not the Week 5 agent loop.

`dispatch_raw()` combines structural parsing and dispatch for isolated tests and
the offline demonstration. Once Member 1's citation validator is merged, the
production call path must parse with `ProposalSet.model_validate_json`, run the
citation validator, and then call `dispatch()`. Production code must not use
`dispatch_raw()` to bypass that validation handoff.

## Files I Created or Changed

### `src/orchestration/tool_dispatcher.py`

This is my Week 4 integration boundary. It contains:

- `TOOL_ACTIONS`: `search_repo`, `read_file`, `run_tests` and `draft_issue`.
- `ToolRisk`, `ApprovalStatus`, `DispatchStatus` and `DispatchCode`.
- `ExecutionContext`: session ID, actor ID and role.
- The `Tool` and `ApprovalGate` protocols.
- `DispatchResult`, including a detached JSON-ready `to_dict()` result.
- `ToolRegistry`, which rejects duplicate, unknown and unsafe registrations.
- `ToolDispatcher.dispatch_raw()` and `ToolDispatcher.dispatch()`.
- A configurable output-size limit of 64,000 bytes by default.

### `src/orchestration/__init__.py`

This file re-exports the public orchestration contracts so teammates can import
from `orchestration` without depending on an internal module path.

### `src/models/__init__.py`

I removed a circular package re-export. A fresh `import rag.pipeline` now works,
while existing direct pipeline imports continue to work.

### `tests/integration/test_tool_dispatcher.py`

The sixteen offline tests use `FakeTool` and `FakeGate` stand-ins. They verify:

- Allow-listed read-only execution.
- Non-tool and unregistered-tool handling.
- Role, argument and approval checks before execution.
- Missing, denied, pending, failing and malformed approval outcomes.
- Exactly one execution after approval.
- Safe tool-error handling with no exception-text leakage.
- Strict JSON, output-schema and output-size enforcement.
- Malformed raw responses and unknown actions.
- Mutation isolation and JSON-ready detached results.
- Rejection of unsafe registry entries.

These are dispatcher tests, not Member 4's real-tool failure matrix.

### `scripts/member2_tool_dispatch_demo.py`

This offline smoke demonstration runs four deterministic scenarios:

1. `read_only_search_executes`
2. `run_tests_without_gate_rejected`
3. `run_tests_with_approving_gate_executes`
4. `unknown_action_rejected`

`DemoSearchRepoTool`, `DemoRunTestsTool` and `DemoApprovingGate` are demonstration
adapters only. They return canned data, execute no tests, read no repository
files and implement no real approval policy. They must not be registered in the
production application.

### Architecture files

- `docs/architecture/qa-agent-architecture (1).drawio` now contains the fifth
  page, "L4 · Tool calling".
- `docs/architecture/l4-tool-calling.png` is the verified export.

Solid outlines identify my components. Dashed outlines identify Member 1's
types/citation validation, Member 3's schemas/tools and Member 5's gate.

## Public Contract for Member 3's Tools

Each concrete tool must satisfy this shape:

```python
class SearchRepoTool:
    name = "search_repo"
    risk = ToolRisk.READ_ONLY
    allowed_roles = ("developer",)

    def validate_arguments(self, arguments): ...  # return normalized dict
    def run(self, arguments, context): ...         # return structured mapping
    def validate_output(self, output): ...         # return JSON-ready dict
```

The tool owns its input and output schemas. The registry owns only the fixed
allow-list, and the dispatcher owns the order in which checks and execution
occur. Member 3 declares the final risk and allowed roles for every tool; my
dispatcher checks the requester's role against those declared roles before
calling the tool's input validator.

## Public Contract for Member 5's Approval Gate

```python
class ApprovalGate:
    def check(self, *, action, arguments, context) -> ApprovalVerdict: ...
```

The dispatcher calls the gate only for `REQUIRES_APPROVAL` tools and only after
argument validation. The gate returns `APPROVED`, `DENIED` or `PENDING`. A
missing gate, exception or malformed verdict fails closed and runs nothing.

## Status and Code Meanings

| Status | Code | Meaning |
| --- | --- | --- |
| `executed` | none | Tool ran once and its output passed validation. |
| `not_a_tool` | none | Action was `propose_test` or `no_action`; nothing ran. |
| `rejected` | `malformed_request` | Response or proposal is invalid. |
| `rejected` | `unknown_tool` | Valid tool action has no registered tool. |
| `rejected` | `unauthorized` | Caller role is not allowed. |
| `rejected` | `invalid_arguments` | Tool rejected its input. |
| `rejected` | `approval_gate_missing` | Required gate is not configured. |
| `rejected` | `approval_unavailable` | Gate failed or returned an invalid verdict. |
| `rejected` | `approval_denied` | Gate denied the request. |
| `awaiting_approval` | `approval_pending` | Human decision is pending. |
| `tool_error` | `execution_failed` | Tool raised during execution. |
| `tool_error` | `invalid_output` | Output failed type, schema, JSON or size checks. |

## Running My Tests and Demo

From the repository root, I run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests/integration \
  -p "test_tool_dispatcher.py" -v
```

Expected result:

```text
Ran 16 tests
OK
```

I run the offline demonstration with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/member2_tool_dispatch_demo.py
```

Neither command needs a model, API key or network connection.

## Known Pre-Existing Test Failures

Commit `5c39b08` deleted
`tests/fixtures/member2/corpus/logs/test_run_2026_09_15.log`, while the RAG
pipeline and evaluation tests still expect it. The affected tests fail on the
pulled `main` and remain unrelated to my Week 4 files. I report this to the team
rather than reverse another member's security-check change on my branch.

## Handoff Checklist

- [ ] Member 3 implements and registers the four real tools.
- [ ] Member 3 confirms `search_repo` wraps
  `RetrievalResult.to_search_repo_output()`.
- [ ] Member 5 implements `ApprovalGate.check` without timeout auto-approval.
- [ ] Member 1 confirms citation validation runs before dispatch.
- [ ] Member 4 runs the failure/authorization suite against the real tools.
- [ ] Member 5 receives my evidence for the Week 4 progress report.
- [x] I kept the LibreOffice lock file out of every commit.

## My Incremental Commits

- `6209aa3` Fix circular model pipeline imports
- `658d3e8` Add safe single-tool dispatcher
- `93f9fb3` Test tool dispatcher safety boundaries
- `3462003` Add offline tool dispatch demonstration
- `718efef` Document the tool calling architecture
- `335f36d` Document the Week 4 tool calling contribution

## Pull Request Description Template

```markdown
## Week 4 – Member 2: Safe single-turn tool dispatcher

### Implemented
- Fixed allow-list registry and single-call dispatcher.
- Public tool and approval-gate contracts.
- Stable structured results and safe failure codes.
- 16 passing offline dispatcher tests.
- Offline demonstration using clearly labelled demo adapters.
- L4 tool-calling architecture page and Member 2 guide.

### Excluded by ownership
- Four real tools: Member 3.
- Approval policy and gate implementation: Member 5.
- Broad failure/authorization evidence suite: Member 4.

### Verification
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover \
  -s tests/integration -p "test_tool_dispatcher.py" -v
PYTHONDONTWRITEBYTECODE=1 python3 scripts/member2_tool_dispatch_demo.py

### Known baseline issue
RAG tests that require the log fixture deleted in commit 5c39b08 still fail.
```

## ClickUp Completion Note Template

```text
I completed Member 2's Week 4 tool-calling orchestration layer.

Delivered:
- ToolDispatcher, ToolRegistry and structured results.
- Tool and ApprovalGate integration contracts.
- 16 passing offline tests and an offline demonstration.
- Updated L4 architecture diagram and first-person guide.

Owned by teammates and not included:
- Real tools (Member 3), approval gate (Member 5), and broad failure evidence
  (Member 4).

Branch: week4-tool-calling-orchestration
Pull request: [URL]
Test evidence: [PATH]
Demo evidence: [PATH]
Architecture: docs/architecture/l4-tool-calling.png
Known baseline issue: missing RAG log fixture after commit 5c39b08.
```

## AI Assistance Declaration

I used OpenAI Codex and Claude Code for planning, implementation review, test
drafting, the demonstration, the architecture page and this guide. I reviewed
the changes, ran the tests and demo, and visually inspected the exported
diagram. I recorded the material assistance in the Week 4 AI Engineering Log.
I remain responsible for the correctness, security and explanation of this
work.

## Definition of Done

- [x] All sixteen dispatcher tests pass offline.
- [x] The demo produces all four expected scenarios.
- [x] Demo adapters are clearly distinguished from production tools.
- [x] Member 3 and Member 5 integration contracts are documented and exported.
- [x] The L4 Draw.io page and PNG are complete.
- [x] The known baseline RAG failure is reported.
- [x] AI assistance is recorded in the repository.
- [ ] Capture sanitized test and demo screenshots.
- [ ] Push the branch and open a pull request against `main`.
- [ ] Add the evidence and PR link to ClickUp.
