# Week 5 Audit: Multi-Step Task vs. the Charter's Promises

**Module:** BSE4104, Emerging Trends in Software Engineering
**Deliverable owner:** Member 1, Project/Requirements Lead
**Reviewing:** `src/agent/task_contract.yaml` and `src/agent/task_adapter.py` (Member 2's Week 5 agent loop) against `docs/requirements/Project_charter and user stories.docx`
**Week:** Week 5
**Status:** Complete; one user story amended (US-9), see §3

## 1. What this audit checks

This week's task is two things: confirm that the multi-step task Member 2 wired up (`task_contract.yaml`, loaded by `task_contract.py`, turned into a real `AgentTask` by `task_adapter.py`) matches what the charter actually promised, and write the code that enforces US-9's stop conditions. The second part is `src/agent/stop_conditions.py`; this document is the first part, plus the one user-story consequence that fell out of writing that code.

The charter's Scope section (item iv) promises "one bounded agent loop (propose, run approved test, observe, summarise, stop) with explicit iteration limits and stop conditions." Scope item (i) promises "one primary end-to-end workflow" that, among other things, lets the agent "receive proposed tests, a sandboxed test run, a failure summary, and a draft issue/PR note." Both are checked below against the contract that actually exists.

## 2. Tools and limits: contract matches the charter

`task_contract.yaml`'s `tools` list (`search_repo`, `read_file`, `run_tests`, `draft_issue`) matches exactly the four tools that have real implementations in `src/tools/`, each with a registered schema in `src/orchestrator/router.py`'s `ToolRegistry`. Nothing in the contract names a tool that does not exist, and nothing implemented is left out of the contract. This is a clean match; no action needed.

`task_contract.yaml`'s `limits` (`max_iterations: 5`, `wall_clock_budget_seconds: 120`) are the two numbers the charter's Scope item (iv) calls for generically ("explicit iteration limits and stop conditions") without naming a specific figure. The comment already in `task_contract.yaml` records this honestly: the 5-iteration cap follows the team's Week 1 to Week 3 design discussion, and the 120-second wall-clock figure is a proposed starting value that no earlier document commits to a specific number. Before this week, the file itself said these limits were "documented intent, not enforced," since `build_stop_evaluator` only raised an error. That is now closed: `StopConditionPolicy`, built in this week's `stop_conditions.py` and wired into `task_adapter.py`, enforces both numbers for real, with 19 unit tests of its own (`tests/test_stop_conditions_unit.py`) and 3 integration tests on the adapter seam (`tests/test_task_adapter.py`) checking it does so correctly, including precedence when more than one condition is true at once.

## 3. US-9's written promise was narrower than what is now enforced (amended)

This week's task description asks for code that enforces "the stop conditions from US-9, such as the maximum number of iterations and the time limit." Reading US-9 as written before this week shows a gap: its acceptance criterion only names one condition, the iteration cap ("the agent's loop halts automatically once a configured maximum iteration count is reached, and this event appears in the trace/log"). It says nothing about a time limit at all, even though the task sheet treats a time limit as part of what US-9 already covers, and even though Member 3's Week 1 "Agent Reasoning Workflow" design note and Member 4's own Week 5 deliverable (`tests/test_stop_conditions.py`, which also records three execution traces under `evidence/traces/`) both describe four conditions, not one: the iteration cap, a wall-clock budget, a repeated identical call, and a step that yields no new information.

Member 4's file is explicit that the `StopConditionPolicy` it defines is "a stand-in... pending `src/agent/stop_conditions.py`," built against the same `agent.loop.StopEvaluator` interface so the real module could slot in without changing their tests' expectations. This week's `src/agent/stop_conditions.py` was written to match that stand-in's behaviour exactly, not just its four condition names: the repeated-call and no-new-information checks both compare only the two most recent observations (an immediate back-to-back repeat), not the whole history, which is narrower than an earlier draft of this module used. To confirm the match is real and not just a shared docstring, the real `StopConditionPolicy` was substituted into Member 4's own four integration scenarios (iteration cap, repeated call, no new information, normal completion) in place of their stand-in, and produced the identical halt reason in every case.

Leaving US-9's written acceptance criterion naming only one of the four conditions would mean the story that is supposed to govern this behaviour undersells what the code actually does and what the rest of the team's own design documents already describe. Following the same precedent used for US-8 in Week 4 and US-11 in Weeks 1 and 2 (widen a story's acceptance criterion when real, verified evidence shows the implementation covers more than the original wording), US-9's acceptance criterion has been widened in `docs/requirements/Project_charter and user stories.docx` from:

> The agent's loop halts automatically once a configured maximum iteration count is reached, and this event appears in the trace/log.

to:

> The agent's loop halts automatically once a configured maximum iteration count is reached, and this event appears in the trace/log. The same automatic halt, each producing its own trace event, also applies when a configured wall-clock time budget is exceeded, when the agent proposes an identical action with identical arguments more than once, and when two consecutive tool calls return identical output with no new information.

The user story's own first half (the "as a Developer" sentence) did not need a change; it already describes the general intent ("stop on its own after a bounded number of steps") broadly enough to cover all four conditions. Only the acceptance criterion was too narrow.

## 4. US-5's failure summary is not yet reachable from the contract (open item, no change made)

Scope item (i) promises the end-to-end workflow produces "a failure summary" as one of its steps, and US-5's acceptance criterion is specific about what that summary must contain: which test failed, a likely cause in one or two sentences citing a specific log line, and a suggested next step. `FailureSummary` has existed as a structured type in `src/models/types.py` since Week 2.

Tracing this forward through this week's contract and the tools it drives finds that `FailureSummary` is not referenced anywhere in the actually-wired pipeline. `task_contract.yaml`'s `goal` text (the `propose_action` v1.1 role and task prompt) does not ask the model to produce one, `src/tools/run_tests.py` returns a `SandboxExecutionResult` of raw `TestResult` entries with no summarisation step, and `src/tools/draft_issue.py`'s schema is generic (title, body, evidence refs) with no field tying it back to a `FailureSummary`. This was confirmed by reading all three files directly, not inferred from their names.

This is not treated as a user-story defect, for the same reason the Week 2 audit gave for `failure_malformed_source_code`: US-5's own wording is accurate about what the finished feature must do, so changing its text would not fix anything. The gap is that no later integration step has yet connected a real `FailureSummary` into the goal prompt or the draft-issue schema. That is implementation work for whichever future week owns that wiring (most likely whoever extends `run_tests` or `draft_issue`, or the prompt-contract owner), not a Week 5 deliverable and not something `stop_conditions.py` touches. It is recorded here so it is not mistaken for an unnoticed gap later, following the same "no document change, open implementation item" precedent used in Week 2.

## 5. Net result

Of the two things this audit was asked to check, the tools-and-limits structure matches the charter cleanly (section 2), and one real mismatch was found and fixed: US-9's acceptance criterion was too narrow for what the charter's own Scope item (iv) and the team's own design documents already called for, and for what this week's `stop_conditions.py` now actually enforces (section 3). A second, unrelated gap was found while tracing the same contract (US-5's failure summary not yet reaching the implemented pipeline) and is recorded as an open item rather than a document change, since the story's wording is already correct (section 4).

## 6. Verification

All 80 tests in a local mirror of the current `src/` and `tests/` pass: this week's 19 new unit tests in `tests/test_stop_conditions_unit.py`, the 3 tests in `tests/test_task_adapter.py` that replace the Week 4 placeholder seam tests, Member 4's own 16 tests in `tests/test_stop_conditions.py` (unchanged, still passing against their own stand-in), and every pre-existing test elsewhere in the suite:

```
PYTHONPATH=src python3 -m unittest discover -s tests -v
...
Ran 80 tests in 3.546s

OK
```

Beyond the automated suite, the real `StopConditionPolicy` was also run directly through Member 4's own four loop-integration scenarios in `tests/test_stop_conditions.py` (in place of their embedded stand-in, without editing their file) and matched every one of their expected halt reasons, confirming the real module is a behavioural match for what their tests already assume, not just a same-named class.

The updated `docs/requirements/Project_charter and user stories.docx` was validated against the original file with the docx skill's XSD validator (`All validations PASSED!`, paragraph count unchanged at 129) and re-rendered to PDF for a page-by-page visual check that the US-9 cell reads correctly and introduces no formatting damage.
