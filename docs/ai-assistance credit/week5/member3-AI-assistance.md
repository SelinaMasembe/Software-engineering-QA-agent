## Week 5 — Agent Task Contract (`task_contract.yaml`), its loader and dataclass, and the contract-to-loop adapter

**Date:** 1st Oct 2026
**Deliverable:** `src/agent/task_contract.yaml`, `src/agent/task_contract.py`, `AgentTaskContract` in `src/models/types.py`, `tests/test_task_contract.py`, `pyyaml` in `requirements.txt`, then the follow-on adapter `src/agent/task_adapter.py` with `tests/test_task_adapter.py`. The adapter and its tests were still uncommitted when this entry was written.

**What I asked the AI for:** I used Claude Code (Claude Sonnet 5.5), which has direct read/write access to the repository, in two sessions. Each prompt told it to explore and confirm the current state of the repo before writing anything, because three other members were changing `src/agent/` the same week. Session 1 asked for the contract file. It also asked for a loader and test only if `models/types.py` already reserved a dataclass shape, and otherwise to stop and ask me. Session 2 asked for an adapter between the contract and what `loop.py` consumes (an `AgentTask` plus an injected stop evaluator). It had to build a real evaluator if Member 1's `stop_conditions.py` existed, and otherwise raise a specific error and not fake enforcement.

**What the AI produced:**

- **Exploration reports, before any code.**
  - `loop.py` exists (Member 2) but does not read any config. Its docstring says it does not parse the task contract.
  - It only takes `AgentTask(goal: str, context: ExecutionContext)` and a `StopEvaluator` Protocol, `evaluate(state: LoopState) -> StopReason | None`.
  - `stop_conditions.py` does not exist on any local or remote branch.
  - `models/types.py` reserved no contract shape.
  - The four tool `name` values are `search_repo`, `read_file`, `run_tests` and `draft_issue`.
  - Nothing in the repo parsed YAML before this week.
  - No iteration-cap or wall-clock number is committed anywhere in the repo, including the `.docx` files.
- **`task_contract.yaml`.** The goal quotes the ROLE and TASK text from `docs/prompts/propose_action/v1.1.md`. The tools are the exact names above. The limits are `max_iterations: 5` and `wall_clock_budget_seconds: 120`, with a comment marking them as documented intent, not enforced.
- **`AgentTaskContract`.** A frozen dataclass added to `models/types.py`. It validates itself: it rejects a blank goal, unknown or duplicate tools, `propose_test` or `no_action` listed as tools, a bool or non-positive `max_iterations`, and a non-positive budget.
- **`load_task_contract()`.** It uses `yaml.safe_load`, rejects missing and unknown keys, and raises `TaskContractError`.
- **`tests/test_task_contract.py`.** 7 tests, covering the points listed under verification below.
- **`task_adapter.py`.**
  - `build_agent_task(contract, *, session_id, actor_id, role)` builds the `AgentTask` from the contract goal and caller-supplied identity.
  - `build_stop_evaluator(contract)` always raises `StopEvaluatorNotImplementedError`. The message names the `evaluate(state: LoopState) -> StopReason | None` interface and the real limits (`max_iterations=5`, `wall_clock_budget_seconds=120`).
- **`tests/test_task_adapter.py`.** 5 tests.

**Verification I performed myself:**

- **Premises checked against the repo.** I told the AI to treat nothing from last week as true. That surfaced two wrong premises. The "5-iteration cap and wall-clock budget committed in Weeks 1-3" is not in the repo. No contract shape was reserved in `models/types.py`, so the AI stopped and asked me. I chose to add the dataclass, use 5 iterations and 120 seconds, and add PyYAML to `requirements.txt`.
- **Contract tests.**
  - The shipped YAML parses into the dataclass.
  - Its tool names equal the real tool classes' `.name` attributes, which the test imports and reads directly.
  - The goal's key sentences appear in `v1.1.md`.
  - 13 deliberately bad YAML files are rejected, and a missing file raises `TaskContractError`.
- **Adapter tests.**
  - The contract goal survives into the `AgentTask`.
  - Empty, whitespace-only, padded and `None` identity values are rejected.
  - The stop-evaluator seam raises the specific error, not a silent no-op.
  - A guard test fails once `stop_conditions.py` exists, so the seam gets revisited.
- **Full suite, run by me.** I ran `PYTHONPATH=src python -m pytest tests -q` and then `git status --short` in my own terminal, not only through the AI.
- **Regression check.** The AI also ran the suite on a clean checkout (changes stashed) and got the same single failure, which shows my work didn't cause it.
- **Final state, confirmed by me today:** `1 failed, 216 passed, 1 warning, 179 subtests passed`. The one failure is `tests/integration/test_rag_pipeline.py::ContractTests::test_manifest_counts_documents_and_chunks`. It also fails without my changes, and I have not investigated why. My brief expected two pre-existing failures, but only this one appears.
- **Collection errors.** Running bare `pytest` from the repo root errors at collection. Test files under `knowledge/corpus/code/` share names with files in `tests/`. This was already the case before my changes, so I ran against `tests/` only.

**What I changed or would still change myself:**

- **120s wall-clock budget.** It is my own proposed number, not a team decision. It needs confirming with Member 1, and the iteration cap of 5 needs confirming against the stop-condition work.
- **Nothing connects the contract to the loop.** `loop.py` does not read the contract, and `build_stop_evaluator` raises until Member 1's `stop_conditions.py` lands. This contract is written ahead of its consumers.
- **Open items outside the code I wrote.**
  - Wiring `contract.tools` into the tool registry.
  - Generating the session id.
  - The `test_manifest_counts_documents_and_chunks` failure.
- **`SandboxNotImplementedError` precedent.** The AI followed it from my description. The class no longer exists in the repo, so it was not copied from code.
- **No prose contract document.** I am writing the Agent Task Contract document myself, as agreed.

**Not AI-generated:** `loop.py`, `ExecutionContext` and the orchestrator, the four tool classes, `models/types.py` before this week, the propose_action prompt and the existing test conventions were written by teammates. Neither session modified `loop.py` or anything under `src/tools/`.

**Data sent to the AI:** Claude Code had direct read/write access to the repository, so it saw the existing code, tests and docs. No personal or production data was sent, only repository content.

**Evidence status:** Re-confirmed today (1st Oct 2026), copied from my terminal:

```
$ PYTHONPATH=src python -m pytest tests -q 2>&1 | tail -6; git status --short
    class TestOutcome(str, Enum):

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/integration/test_rag_pipeline.py::ContractTests::test_manifest_counts_documents_and_chunks
1 failed, 216 passed, 1 warning, 179 subtests passed in 15.03s
?? src/agent/task_adapter.py
?? tests/test_task_adapter.py
```

Still to do: save a screenshot of this run to `evidence/screenshots/week5/`, commit the adapter and its tests, and investigate or hand off the failing manifest test.

---
