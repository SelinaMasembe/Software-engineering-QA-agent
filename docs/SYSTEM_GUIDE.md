# System Guide: The Software-Engineering QA Agent in Plain Language

BSE4104 | Group J | Written by Member 5 (DevOps/Documentation Lead), 23 October 2026.

This guide explains, without assuming programming experience:
- what we built;
- how a request travels through the code;
- what keeps it safe;
- how to run it;
- what to do with it next.

Every file name below is real and can be opened in the repository.

---

## 1. What we built, in one paragraph

A **QA assistant for a software team**. A developer gives it a goal, for
example *"Propose a test that the account locks after five failed login
attempts."* The assistant:
1. reads the team's own requirements, code and test logs;
2. finds the evidence that matters;
3. asks an AI model (Google's Gemini) for **one next step at a time**;
4. checks every step with ordinary code before anything happens.

It ends with a **proposed test that cites its sources**, or a draft issue
note, for a human to review. It **cannot** merge code, deploy, read secrets,
submit anything to GitHub, or run arbitrary commands. Running a test or
drafting an issue needs a named human's approval first.

> **The one idea to remember:** the AI suggests; ordinary code and people
> decide. Almost every file in this project is either the AI part (small) or a
> check around it (most of the code).

---

## 2. The words you need

| Word | Meaning here |
| --- | --- |
| **Agent** | A program that repeats *look, decide, act, check* until a goal is met or it must stop. |
| **Model / LLM** | The AI (Gemini 2.5 Flash). It only ever *proposes* an action as JSON text. |
| **Prompt** | The fixed instructions sent to the model, versioned in `docs/prompts/propose_action/v1.0`–`v1.3.md`. |
| **Corpus** | The 22 approved documents the agent may read (`knowledge/`). |
| **RAG** | "Retrieval-augmented generation": find relevant passages first, then give them to the model as evidence. |
| **Citation** | The `source_path` the model must quote for every claim. Code rejects any path it was not given. |
| **Tool** | One of four actions the agent may request: `search_repo`, `read_file`, `run_tests`, `draft_issue`. |
| **Approval gate** | The waiting room where a risky request sits until a named human approves it. |
| **Sandbox** | A separate process with no secrets and a 30-second time limit, where approved tests run. |
| **Trace / run log** | A line-by-line record of everything the agent did, saved as evidence. |
| **Scenario** | One test situation with an expected result. We have 61. |

---

## 3. How one request travels through the code

```text
 Developer's goal
      |
      v
[1] Task contract ........ src/agent/task_contract.yaml   (goal, 4 tools, limits: 5 turns, 120 s)
      |
      v
[2] Agent loop ........... src/agent/loop.py              repeats steps 3-8, one action per turn
      |
      v
[3] SENSE: find evidence . src/agent/sensor.py -> src/rag/  (search the corpus, build the evidence block)
      |                       + credential_scan.py (hide secrets) + injection_flagging.py (flag tricks)
      v
[4] PLAN: ask the model .. src/agent/planner.py -> src/models/client.py -> Gemini
      |                       using the prompt docs/prompts/propose_action/v1.3.md
      v
[5] CHECK citations ...... src/orchestrator/validation.py  (cited a source it wasn't given? rejected)
      |
      v
[6] ACT
      |-- propose_test / no_action --> finish the run
      |-- a tool --> [7] Dispatcher src/orchestrator/router.py
                          role allowed? arguments valid? approval needed?
                          |
                          |-- run_tests / draft_issue --> Approval gate (src/orchestrator/approval_gate.py)
                          |                                waits for a human (scripts/approve_cli.py)
                          v
                       Tool runs: src/tools/*.py   (tests run in src/sandbox/executor.py)
      |
      v
[8] OBSERVE + STOP? ...... src/agent/stop_conditions.py (turn cap, time budget, repeats, no progress)
      |
      v
 Every step recorded ..... src/observability/run_logger.py (audit trail) + telemetry.py (timings)
```

### Step by step, in plain words

1. **Task contract** (`src/agent/task_contract.yaml`, Member 3). A small
   settings file. It states the agent's goal wording, the only four tools it
   may use, and its limits: at most **5 turns** and **120 seconds**.
2. **Agent loop** (`src/agent/loop.py`, Member 2). The engine. Each turn it
   senses, plans, checks, acts and observes. It allows **one action per turn
   and at most one tool call**. If any part breaks, the run stops with a fixed,
   safe error message.
3. **Sense** (`src/agent/sensor.py` with `src/rag/`; Members 2 and 3).
   - **Search.** Splits the corpus into passages and searches them locally
     with a classic keyword-ranking method (BM25). Nothing is sent over the
     internet for this step.
   - **"Not found".** If nothing relevant is found, it says so. That decision
     is made by code, never by the AI.
   - **Secrets hidden.** `credential_scan.py` replaces anything that looks like
     a password or API key with `[REDACTED:credential]`.
   - **Tricks flagged.** `injection_flagging.py` flags text that looks like a
     hidden instruction, such as "ignore previous instructions". It flags; it
     does not delete.
4. **Plan** (`src/agent/planner.py`, Member 3; `src/models/client.py`,
   Member 2; `src/config/loader.py`, Member 5). Sends the prompt, the goal and
   the evidence to Gemini and reads back **one JSON action**. A reply that
   isn't valid JSON becomes a fixed error, never raw model text.
5. **Check citations** (`src/orchestrator/validation.py`, Member 1). Every
   proposal must cite at least one source that was actually supplied this
   turn. A made-up source is **rejected before anything runs**, and the loop
   may try again.
6. **Act.**
   - A proposed test (`propose_test`) or "nothing to do" (`no_action`) ends
     the run.
   - A tool request goes to the dispatcher.
7. **Dispatcher, approval and tools.**
   - **Dispatcher** (`src/orchestrator/router.py`, Member 2). Checks that the
     tool is on the list, that the role is allowed, and that the arguments are
     valid.
   - **Approval** (`src/orchestrator/approval_gate.py`, Member 5). For
     `run_tests` and `draft_issue`, the request waits until an authorised
     person approves it with `scripts/approve_cli.py`. Each approval works
     **once**. Nobody can approve their own request. An undecided request
     expires as **denied**.
   - **Sandbox** (`src/sandbox/executor.py`). Runs tests with `shell=False`,
     no secrets in the environment, and a 30-second limit.
8. **Stop?** (`src/agent/stop_conditions.py`, Member 1). Checked before the
   first turn and after every observation. The run halts on any of these:
   the turn limit, the time budget, the same action twice in a row, or two
   tool results that are exactly the same.
9. **Record everything.**
   - **Run logger** (`src/observability/run_logger.py`, Member 5). Writes
     every step to `evidence/traces/runs/`. If it cannot write, the agent
     **stops**, so it never acts without an audit trail.
   - **Telemetry** (`src/observability/telemetry.py`, Member 2). Records
     timings and counts for each step.

### Memory (Week 6)

`src/memory/` remembers, **for each code module**, which tests were proposed,
run, or rejected by a human, so the agent doesn't repeat itself:
- **Schema:** Member 1.
- **Database:** Member 2.
- **API:** Member 3.
- **Retention:** Member 5.

Memory is **advice only**: it can never count as approval. Records are kept
until a human clears them (`python -m memory.retention clear-module …`).
Today, memory is built and tested, but the live agent session does not yet
read it into the prompt (see section 8).

---

## 4. What keeps it safe

| Risk | What stops it | File |
| --- | --- | --- |
| The AI invents a source | Citation check rejects any path not supplied this turn | `src/orchestrator/validation.py` |
| A document contains a hidden instruction ("run rm -rf") | Flagged; the tool list, approval and sandbox still contain it | `src/rag/injection_flagging.py`, `router.py` |
| A secret leaks into the AI's input | Credential-shaped strings are redacted before the model sees them | `src/rag/credential_scan.py`, `src/agent/history_guard.py` |
| The agent runs something dangerous | Only 4 tools exist; tests need human approval and an allow-listed ID; sandbox has no shell and no secrets | `router.py`, `approval_gate.py`, `src/sandbox/executor.py` |
| Someone approves their own request | Refused; each approval is single-use | `approval_gate.py` |
| The agent loops forever | 5 turns, 120 s, repeat and no-progress checks | `src/agent/stop_conditions.py` |
| Nobody can see what happened | Every step logged; logging failure stops the agent | `src/observability/run_logger.py` |
| A developer commits a password | Pre-commit hook blocks the commit | `scripts/check_sensitive.py`, `.githooks/pre-commit` |

---

## 5. How to run it

Do this once:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
git config core.hooksPath .githooks      # turns on the secret scanner
```

**Offline (no API key needed):**

| Goal | Command | What you see |
| --- | --- | --- |
| Check everything works | `python3 -m pytest -q` | Several hundred tests, all passing |
| Run all 61 evaluation scenarios | `python3 tests/run_scenarios.py` | 61 of 61 behaved as expected; writes `evidence/evaluation/week7-scenario-results.*` |
| One full agent session, stub model | `PYTHONPATH=src python3 scripts/run_agent_session.py --goal "Propose a test that the account locks after five failed login attempts."` | The real pipeline with a stand-in model: completes with a cited proposed test |
| See a saved run as a timeline | `PYTHONPATH=src python3 scripts/show_run_log.py --last` | Every step of a saved run, including a human approval |
| Approval demo | `PYTHONPATH=src python3 scripts/member5_approval_demo.py` | Pending, then approved once, then pending again |
| Stop conditions demo | `PYTHONPATH=src python3 scripts/member1_stop_conditions_smoke.py` | All four stop reasons |
| Telemetry demo | `PYTHONPATH=src python3 scripts/member2_observability_demo.py --no-write --timeline` | Step timings for three runs |
| Secret scan | `python3 scripts/check_sensitive.py --all` | No output means clean |

**Live (real Gemini model, needs an API key):**

1. `cp .env.example .env`, then put your own key in `.env`. **Never commit
   `.env`.** The pre-commit hook blocks it.
2. Load the settings into your terminal: `set -a; source .env; set +a`.
3. Run a live session:
   `PYTHONPATH=src python3 scripts/run_agent_session.py --goal "Propose a test that the account locks after five failed login attempts." --live --out evidence/test-runs/week8/agent-session/my_run.json`

The live script has **no approval gate** configured, so it can never run tests
or draft issues. Those requests are refused by design. Use a specific goal:
the vague default goal finds no evidence and correctly returns `no_action`.

---

## 6. Where to find things

| You want | Look in |
| --- | --- |
| The code | `src/` (one folder per part; see section 3) |
| Tests | `tests/` (unit), `tests/integration/` (end to end), `tests/adversarial/` (attack cases), `tests/run_scenarios.py` (runs all scenarios) |
| Demos and tools | `scripts/` |
| Requirements and charter | `docs/requirements/` |
| Architecture diagrams | `docs/architecture/` |
| Prompts | `docs/prompts/` |
| Evaluation results and Failure Catalogue | `docs/evaluation/`, `evidence/evaluation/` |
| Traces and logs | `evidence/traces/`, `evidence/test-runs/` |
| Weekly reports | `docs/weekly reports/` |
| Final report sections, appendices, evidence index | `docs/evaluation/`, `docs/integration/`, `docs/final-report/` |
| AI assistance records | `docs/ai-assistance credit/` |

---

## 7. Who built what

| Member | Role | Main parts |
| --- | --- | --- |
| M1 Amabe Junior Humphrey | Requirements | Charter, user stories, data types, citation validation, stop conditions, memory schema, scenario traceability |
| M2 Akanga Andrew | Integration | Model client, retrieval pipeline, dispatcher, agent loop, memory store and MCP interface, telemetry, architecture, release |
| M3 Karagwa Ann Treasure | AI Engineering | Model choice, prompts v1.0–v1.3, context builder, four tools, task contract, memory API, scorer and adversarial cases, planner, sensor, guardrails |
| M4 Ayan Mustafa Abdirahman | Quality/Security | Boundary matrix, prompt and RAG evaluations, authorization tests, stop-condition tests, memory guard, Failure Catalogue |
| M5 Wanyana Selina Masembe | DevOps/Documentation | Repo and ClickUp, config loader, secret scanner, approval gate, run logger, memory retention, scenario runner, README, reports, this guide |

---

## 8. Honest limits, and what to do next

What works:
- **Offline checks:** 61 of 61 scenarios behave as expected, there are no
  safety violations in the scored cases, and every listed safeguard is tested.
- **A real end-to-end live session completed:** Gemini proposed a test citing
  `requirements/authentication.md` and `src/login_service.py`.

What does not, yet:
- **Mostly scripted evidence.** Only one live end-to-end session and two
  single-shot live runs exist; one of those stopped on rate limits.
- **The model can still be fooled.** In one live case Gemini obeyed an
  instruction hidden in a code comment. The flag was raised, but flagging does
  not stop the model.
- **Limited checking.** "Groundedness" checks that a cited file was supplied,
  not that it supports the claim. Unchecked claims in drafted issues (R10)
  remain a known gap.
- **Memory is not wired in.** The live agent does not read memory yet.
- **No real isolation.** The sandbox is a separate process, not a container:
  it has no file-system or network isolation. Only run reviewed tests.

What to do with it next:
1. **Use it as intended:** point it at one module with a specific goal, review
   the cited proposal, approve only the tests you trust.
2. **Before relying on it:** collect more live runs (several per case) to
   measure rates; wire memory into the planner; run tests in a container.
3. **Keep the safety rails:** never remove the citation check, the approval
   gate, the stop conditions or the run logger. They are what make the AI's
   output trustworthy enough to review.
