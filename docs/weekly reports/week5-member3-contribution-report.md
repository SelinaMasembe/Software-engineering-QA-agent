# Week 5 Contribution Report: Member 3 (AI Engineering Lead)

**Date:** 1st Oct 2026
**Branch:** `agent_task_contract`
**Topic:** Agent Task Contract and the adapter that turns it into what the agent loop consumes

## Summary

The agent loop (Member 2) has no configuration of its own. This week I built the config file it is driven by, the typed loader for that file, an adapter from the contract to the loop's `AgentTask`, and a runner that builds a loop from the contract without changing `loop.py`. The adapter's stop-evaluator half was first left open as a deliberate error, because Member 1's `stop_conditions.py` had not landed. Member 1 has since landed it and closed that seam. With the real contract, adapter, stop policy and loop, a session halts at the contract's iteration cap in the tests. The real sensor, planner and trace sink are not wired, so a live session cannot run yet.

## What I delivered

| Deliverable | File | Status |
|---|---|---|
| Contract config (goal, four tools, limits) | `src/agent/task_contract.yaml` | Committed |
| Typed shape | `AgentTaskContract` in `src/models/types.py` | Committed |
| Loader and validation | `src/agent/task_contract.py` (`load_task_contract`, `TaskContractError`) | Committed |
| Loader tests (7) | `tests/test_task_contract.py` | Committed |
| PyYAML dependency | `requirements.txt` | Committed |
| Contract-to-loop adapter | `src/agent/task_adapter.py` | Committed |
| Adapter tests | `tests/test_task_adapter.py` | Committed; rewritten by Member 1 when the seam closed |
| Session runner (`build_agent_session`) | `src/agent/runner.py` | Committed on branch `agent-runner-contract-wiring` |
| Runner integration tests (10) | `tests/integration/test_agent_runner.py` | Committed on the same branch |
| Tool-registry check (`ToolContractMismatchError`) | `src/agent/runner.py` | Committed on the same branch (cca76a7) |
| Fixture fix: delete duplicate `test_run_2026_09_15.log` | `tests/fixtures/member2/corpus/logs/` | Committed |
| AI-assistance entry | `docs/ai-assistance credit/week5/member3-AI-assistance.md` | Written |

## What I found before building

I had the AI re-explore the repo before each step and report what was actually there. This changed the work in two places.

- **`loop.py` does not read a config file.** It takes `AgentTask(goal, context)` and an injected `StopEvaluator` (`evaluate(state) -> StopReason | None`). The contract is therefore written ahead of its consumer.
- **`models/types.py` reserved no contract shape.** I chose to add one dataclass, `AgentTaskContract`.
- **The 5-iteration cap and wall-clock budget are not committed anywhere in the repo.** No document or code gives a number, including the `.docx` files. I chose 5 iterations and 120 seconds.
- **`stop_conditions.py` did not exist on any branch at first.** The adapter therefore raised a specific error for the evaluator half and did not fake enforcement. Member 1 landed it later in the week (commit fe70967) and updated the adapter and its tests. Its real interface matches what the error message named: `StopConditionPolicy(*, max_iterations, wall_clock_budget_seconds, clock)` with `evaluate(state) -> StopReason | None`.
- **Nothing in the repo parsed YAML before.** I added PyYAML to `requirements.txt` and use `safe_load`.
- **Tool names confirmed from code:** `search_repo`, `read_file`, `run_tests`, `draft_issue`.

## Design decisions

- The goal text quotes the ROLE and TASK sentences in `docs/prompts/propose_action/v1.1.md` verbatim.
- Unknown keys in the YAML are rejected, and `AgentTaskContract` validates itself on construction. It rejects unknown or duplicate tools, `propose_test` or `no_action` as tools, bool or non-positive iteration caps, and non-positive budgets.
- Session id, actor id and role are runtime values, so `build_agent_task` takes them from the caller and builds `ExecutionContext` with keyword arguments, as every existing test and script does.
- `build_stop_evaluator` now returns `StopConditionPolicy.from_contract(contract)`. Until Member 1's module landed it raised `StopEvaluatorNotImplementedError`, naming the interface to build against.
- The stop policy is stateful: it starts its wall-clock on its first `evaluate()` call. `AgentSession` keeps the single evaluator inside the loop, so `resume` reuses it and the budget does not reset.
- `build_agent_session` rejects a dispatcher whose `ToolRegistry` does not hold exactly `contract.tools`. I chose an exact match over "at least these four". `ToolRegistry` only accepts the four executable tools and no registry in the repo holds any other, so there is no legitimate extra to allow. A contract can grant fewer than four tools, though, and a registry holding a tool the contract never granted would widen the agent's permissions. The original runner tests registered only `search_repo`, so I changed only how they build the registry. Their assertions are untouched.
- The runner is a new module, `src/agent/runner.py`. `loop.py` already exposed `AgentLoop(...).run(task)` and `.resume(result)`, so no change to it was needed. The sensor, planner, dispatcher and trace sink are passed in by the caller.

## Verification

- **Contract tests:**
  - The shipped YAML parses into the dataclass.
  - Its tool names equal the real tool classes' `.name` values.
  - Its goal sentences appear in `v1.1.md`.
  - 13 bad files are rejected, and a missing file raises `TaskContractError`.
- **Adapter tests:**
  - The contract goal reaches the `AgentTask`.
  - Empty, padded and `None` identity values are rejected.
  - Before `stop_conditions.py` landed, the seam raised the specific error and a guard test failed when the file appeared.
  - Member 1 then replaced those tests: the evaluator is built from the real contract values and actually halts at the contract's iteration cap.
- **Runner integration tests (5 of the 10)**, using the real YAML, adapter, stop policy, `AgentLoop`, `ToolDispatcher` and `ToolRegistry`:
  - The session is built from the contract values.
  - Bad identity and a non-contract are rejected.
  - A grounded proposal completes in one turn.
  - The contract's goal reaches the planner.
  - A planner that never finishes is halted with `ITERATION_CAP` at exactly 5 iterations, and the tool ran exactly 5 times.
  - The sensor, planner and trace sink are scripted. No model or network call is made.
- **Tool-registry check tests (the other 5)**, in the same file:
  - A registry that matches `contract.tools` exactly succeeds.
  - A registry missing a contract tool is rejected, with the tool's name in the error.
  - A registry holding a tool the contract doesn't declare is rejected, with the tool's name in the error.
  - Missing and extra tools are both named together.
  - A dispatcher with no `ToolRegistry` fails closed instead of skipping the check.
- **First full run**, in my own terminal: `1 failed, 216 passed`. The one failure also failed on a clean checkout with my changes stashed, so my work did not cause it.
- **Run after the fixture fix**, in my own terminal: `217 passed, 1 warning, 179 subtests passed`, no failures.
- **Run after adding the runner**, with Member 1's work pulled in: `258 passed, 1 warning, 188 subtests passed`, no failures.
- **Final full run**, after adding the tool-registry check: `263 passed, 1 warning, 188 subtests passed in 16.09s`, no failures, from my own terminal (screenshot in `evidence/screenshots/week5/`).

## The failing test: cause and fix

`test_rag_pipeline.py::ContractTests::test_manifest_counts_documents_and_chunks` expects 3 documents in the fixture corpus, and the loader found 4. `tests/fixtures/member2/corpus/logs/` held both `test_run_2026_09_15.log` and `test_run_2026_09_15.txt`. Selina's commit f795b75 had renamed the original `.log` to `.txt` to pass the `*.log` sensitive-data rule. My Week 4 commit cfb84b6 re-added the `.log` without noticing the `.txt` already existed. The fix was to delete the redundant `.log`. The `.txt` is the file the Week 3 evaluation document cites.

## Open items

1. **Stale ignore entry.** `.sensitive-scan-ignore` has one entry, for the deleted `.log`. It is now unneeded and its comment is out of date. I have not decided whether to remove the file.
2. **Collection errors.** A bare `pytest` from the repo root errors at collection, because files under `knowledge/corpus/code/` share names with files in `tests/`. Running against `tests/` avoids it. This was already the case before my changes.
3. **Limits to confirm.** The 120s wall-clock budget is my proposed number and needs confirming with Member 1. The iteration cap of 5 needs confirming against their stop-condition work.
4. **Not yet end to end.** There is no real `ContextSensor` or `Planner` wrapping retrieval and the propose_action model call, and Member 5's trace sink does not exist yet. The runner tests use scripted stand-ins, so the real model call and retrieval were not run.
5. **Caller responsibilities.** Session id and role come from whoever calls `build_agent_session`. A custom dispatcher must expose a `.registry`, otherwise the runner refuses it.
6. **Housekeeping.** Open the PR from `agent-runner-contract-wiring`. The Claude co-author line was removed by amending the commit. The original (188aba6) had already been pushed, and I have since force-pushed, so the remote head has no co-author line. Also keep the screenshot of the 263-pass run in `evidence/screenshots/week5/`.

## Constraints respected

I did not modify `loop.py`, `src/tools/`, or `models/types.py` beyond the one dataclass, and wiring the loop stayed additive. I did not modify `stop_conditions.py`, which is Member 1's. The Agent Task Contract prose document is my own separate deliverable and is not part of this report.
