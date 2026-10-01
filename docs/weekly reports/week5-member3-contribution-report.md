# Week 5 Contribution Report: Member 3 (AI Engineering Lead)

**Date:** 1st Oct 2026
**Branch:** `agent_task_contract`
**Topic:** Agent Task Contract and the adapter that turns it into what the agent loop consumes

## Summary

The agent loop (Member 2) has no configuration of its own. This week I built the config file it will eventually be driven by, the typed loader for that file, and an adapter from the contract to the loop's `AgentTask`. The stop-evaluator half of the adapter is deliberately left open, because Member 1's `stop_conditions.py` has not landed. Nothing connects the contract to the loop yet.

## What I delivered

| Deliverable | File | Status |
|---|---|---|
| Contract config (goal, four tools, limits) | `src/agent/task_contract.yaml` | Committed |
| Typed shape | `AgentTaskContract` in `src/models/types.py` | Committed |
| Loader and validation | `src/agent/task_contract.py` (`load_task_contract`, `TaskContractError`) | Committed |
| Loader tests (7) | `tests/test_task_contract.py` | Committed |
| PyYAML dependency | `requirements.txt` | Committed |
| Contract-to-loop adapter | `src/agent/task_adapter.py` | Committed |
| Adapter tests (5) | `tests/test_task_adapter.py` | Committed |
| Fixture fix: delete duplicate `test_run_2026_09_15.log` | `tests/fixtures/member2/corpus/logs/` | Staged, not committed |
| AI-assistance entry | `docs/ai-assistance credit/week5/member3-AI-assistance.md` | Written |

## What I found before building

I had the AI re-explore the repo before each step and report what was actually there. This changed the work in two places.

- **`loop.py` does not read a config file.** It takes `AgentTask(goal, context)` and an injected `StopEvaluator` (`evaluate(state) -> StopReason | None`). The contract is therefore written ahead of its consumer.
- **`models/types.py` reserved no contract shape.** I chose to add one dataclass, `AgentTaskContract`.
- **The 5-iteration cap and wall-clock budget are not committed anywhere in the repo.** No document or code gives a number, including the `.docx` files. I chose 5 iterations and 120 seconds.
- **`stop_conditions.py` does not exist on any branch.** The adapter therefore raises a specific error for the evaluator half and does not fake enforcement.
- **Nothing in the repo parsed YAML before.** I added PyYAML to `requirements.txt` and use `safe_load`.
- **Tool names confirmed from code:** `search_repo`, `read_file`, `run_tests`, `draft_issue`.

## Design decisions

- The goal text quotes the ROLE and TASK sentences in `docs/prompts/propose_action/v1.1.md` verbatim.
- Unknown keys in the YAML are rejected, and `AgentTaskContract` validates itself on construction. It rejects unknown or duplicate tools, `propose_test` or `no_action` as tools, bool or non-positive iteration caps, and non-positive budgets.
- Session id, actor id and role are runtime values, so `build_agent_task` takes them from the caller and builds `ExecutionContext` with keyword arguments, as every existing test and script does.
- `build_stop_evaluator` always raises `StopEvaluatorNotImplementedError`. The message names the interface Member 1's code must satisfy and the real limits (5 iterations, 120 seconds).

## Verification

- **Contract tests:**
  - The shipped YAML parses into the dataclass.
  - Its tool names equal the real tool classes' `.name` values.
  - Its goal sentences appear in `v1.1.md`.
  - 13 bad files are rejected, and a missing file raises `TaskContractError`.
- **Adapter tests:**
  - The contract goal reaches the `AgentTask`.
  - Empty, padded and `None` identity values are rejected.
  - The seam raises the specific error.
  - A guard test fails when `stop_conditions.py` is added, as a prompt to wire the real evaluator.
- **First full run**, in my own terminal: `1 failed, 216 passed`. The one failure also failed on a clean checkout with my changes stashed, so my work did not cause it.
- **Final full run**, in my own terminal after the fix: `217 passed, 1 warning, 179 subtests passed`, no failures.

## The failing test: cause and fix

`test_rag_pipeline.py::ContractTests::test_manifest_counts_documents_and_chunks` expects 3 documents in the fixture corpus, and the loader found 4. `tests/fixtures/member2/corpus/logs/` held both `test_run_2026_09_15.log` and `test_run_2026_09_15.txt`. Selina's commit f795b75 had renamed the original `.log` to `.txt` to pass the `*.log` sensitive-data rule. My Week 4 commit cfb84b6 re-added the `.log` without noticing the `.txt` already existed. The fix was to delete the redundant `.log`. The `.txt` is the file the Week 3 evaluation document cites.

## Open items

1. **Stale ignore entry.** `.sensitive-scan-ignore` has one entry, for the deleted `.log`. It is now unneeded and its comment is out of date. I have not decided whether to remove the file.
2. **Collection errors.** A bare `pytest` from the repo root errors at collection, because files under `knowledge/corpus/code/` share names with files in `tests/`. Running against `tests/` avoids it. This was already the case before my changes.
3. **Limits to confirm.** The 120s wall-clock budget is my proposed number and needs confirming with Member 1. The iteration cap of 5 needs confirming against their stop-condition work.
4. **Stop evaluator.** `stop_conditions.py` has not landed. Once it does, `build_stop_evaluator` should return the real evaluator.
5. **Not yet connected.** `loop.py` does not read the contract. `contract.tools` is not yet wired into the tool registry, and session-id generation is undecided.
6. **Housekeeping.** Commit the staged deletion and the two Week 5 documents, and save a screenshot of the green run to `evidence/screenshots/week5/`.

## Constraints respected

I did not modify `loop.py`, `src/tools/`, or `models/types.py` beyond the one dataclass. I also did not modify the contract files or any `stop_conditions.py` when building the adapter. The Agent Task Contract prose document is my own separate deliverable and is not part of this report.
