# Software-Engineering QA Agent

An AI-native QA assistant for a software team, built by Group J for BSE4104
Emerging Trends in Software Engineering (Makerere University, 2026/2027).

The agent reads team-owned requirements, source code and test logs, proposes
grounded tests, runs only human-approved tests in a sandbox, and drafts
failure notes for human review. The model interprets and proposes;
deterministic code and people control permissions, validation, execution and
anything with side effects.

```text
requirements / code / logs
  -> retrieve evidence (RAG) -> model proposes ONE next action
  -> citation check -> dispatcher (role + arguments) -> human approval
  -> sandboxed tool -> observe -> repeat or stop -> draft for human review
```

## Safety Boundaries

| The agent may                                       | The agent must not                                   |
| --------------------------------------------------- | ---------------------------------------------------- |
| Read approved requirements, code and test logs      | Access production systems or deploy                  |
| Propose tests and diagnoses that cite evidence      | Merge pull requests or submit issues                 |
| Call four registered tools through the dispatcher   | Run arbitrary shell commands or unlisted tests       |
| Run manifest-listed tests after human approval      | Read or expose secrets                               |
| Prepare local issue drafts                          | Make final engineering decisions without a human     |

How these are enforced in code:

- **Citation validation:** every proposal must cite a source it was actually given.
- **Fixed tool registry with role checks.**
- **Human approval gate** for `run_tests` and `draft_issue`.
- **Sandbox:** tests run with a stripped environment and a timeout.
- **Bounded agent loop:** an iteration cap, a time budget, repeat detection and a no-progress check.
- **Run log:** every run is saved to `evidence/traces/runs/`.
- **Pre-commit secret scanner.**

## Architecture

| Step              | Component                                                  | Code                                                                |
| ----------------- | ---------------------------------------------------------- | ------------------------------------------------------------------- |
| 1. Corpus         | Curated, provenance-tagged documents                       | `src/ingestion/tag_provenance.py`, `knowledge/`                     |
| 2. Retrieval      | Boundary-aware chunks, local BM25, `not_in_corpus` decision | `src/rag/chunking.py`, `retriever.py`, `retrieval.py`               |
| 3. Context        | Evidence block plus the sources it is safe to cite         | `src/rag/context_builder.py`                                        |
| 4. Planning       | Model proposes one action (`propose_action` v1.1)          | `src/models/client.py`, `docs/prompts/propose_action/`              |
| 5. Validation     | Reject untraceable or fabricated citations                 | `src/orchestrator/validation.py`                                    |
| 6. Dispatch       | Registry, role and argument checks, approval, output limits | `src/orchestrator/router.py`, `src/orchestrator/approval_gate.py`   |
| 7. Tools          | `search_repo`, `read_file`, `run_tests`, `draft_issue`     | `src/tools/`, `src/sandbox/executor.py`                             |
| 8. Agent loop     | Sense, plan, validate, act, observe, stop or pause         | `src/agent/loop.py`, `stop_conditions.py`, `task_contract.yaml`     |
| 9. Observability  | Every run saved as JSON Lines evidence                     | `src/observability/run_logger.py`                                   |

Diagrams:

- `docs/architecture/l3-retrieval-pipeline.png`
- `docs/architecture/l4-tool-calling.png`
- `docs/architecture/l5-agent-loop.png`
- source: `docs/architecture/qa-agent-architecture (1).drawio`

## Progress by Week

Roles: M1 Project/Requirements, M2 Application/Integration, M3 AI Engineering,
M4 Quality/Security, M5 DevOps/Documentation.

| Week | Focus | Delivered | Key paths |
| --- | --- | --- | --- |
| 1 | Charter and boundaries | Charter, 12 user stories, AI boundary matrix, architecture, GitHub and ClickUp setup (M1–M5) | `docs/requirements/`, `docs/architecture/`, `evidence/screenshots/week1/` |
| 2 | Model integration and prompts | Domain types (M1); model client and baseline pipeline (M2); `propose_action` prompt v1.0/v1.1, prompt loader, model selection (M3); 10-case prompt evaluation (M4); environment config and `.env.example` (M5) | `src/models/`, `src/prompts/`, `src/config/`, `docs/evaluation/week2-ten-case-evaluation.md` |
| 3 | Retrieval and provenance | Curated corpus and source register (M1); chunking, BM25 retrieval, `not_in_corpus` (M2); context builder (M3); 15-case RAG evaluation (M4); pre-commit sensitive-data scanner (M5) | `src/ingestion/`, `src/rag/`, `docs/evaluation/week3-fifteen-case-rag-evaluation.md`, `scripts/check_sensitive.py` |
| 4 | Tools and approval | Tool-schema audit and citation validation (M1); tool dispatcher (M2); four tools and sandbox (M3); authorization and failure tests (M4); human approval gate and CLI (M5) | `src/orchestrator/`, `src/tools/`, `src/sandbox/`, `docs/evaluation/week4-tool-authorization-evaluation.md` |
| 5 | Bounded agent | Stop conditions and charter audit (M1); agent loop (M2); agent task contract (M3); stop-condition tests and three execution traces (M4); run logger saving every run (M5) | `src/agent/`, `src/observability/`, `evidence/traces/` |
| 6 | Memory, state, interoperability | Upcoming | |
| 7 | Evaluation, observability, guardrails | Upcoming: 30-scenario evaluation, failure catalogue | |
| 8 | Final integration and presentation | Upcoming | |

Weekly progress reports are in `docs/weekly reports/`. AI-assistance records
are in `docs/ai-assistance credit/`.

## Repository Layout

```text
src/                      application code (run with pytest.ini or PYTHONPATH=src)
  agent/                  agent loop, stop conditions, task contract (YAML + loader + adapter)
  config/                 environment settings loader
  ingestion/              corpus collection and provenance register
  models/                 model client and shared domain types
  observability/          run logger (trace sink) for evidence/traces/runs/
  orchestrator/           tool dispatcher, citation validation, approval gate
  prompts/                versioned prompt loader
  rag/                    chunking, retrieval, context builder, baseline pipeline
  sandbox/                sandboxed pytest executor
  tools/                  search_repo, read_file, run_tests, draft_issue
scripts/                  smoke tests, demos, approval CLI, secret scanner, docx generators
tests/                    unit tests; tests/integration/ end-to-end tests; tests/fixtures/
docs/                     requirements, architecture, prompts, evaluation, integration, reports
knowledge/                curated corpus (corpus/) and source-register.json/.md
evidence/                 screenshots, demo captures, execution traces
.githooks/pre-commit      runs scripts/check_sensitive.py on staged files
```

## Setup

Requirements: Python 3.10+, and a Google AI Studio API key for live model
calls only. Everything else runs offline. Node.js is needed only to rebuild
the Member 2 `.docx` deliverables (`scripts/generate_week*_member2_docx.js`).

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
git config core.hooksPath .githooks        # enable the secret scanner once per clone
```

For live model calls, create a local `.env` from the template and load it:

```bash
cp .env.example .env                        # then add your key; never commit .env
set -a; source .env; set +a
```

## Running Tests

```bash
python3 -m pytest -q                        # full offline suite (pytest.ini sets paths)
python3 scripts/check_sensitive.py --all    # secret / personal-data scan, must exit 0
```

To run one area:

```bash
PYTHONPATH=src python3 -m unittest tests.test_rag_eval -v                       # 15-case RAG evaluation
PYTHONPATH=src python3 -m unittest tests.integration.test_router -v             # dispatcher
PYTHONPATH=src python3 -m unittest tests.integration.test_approval_gate -v      # approval gate
PYTHONPATH=src python3 -m unittest tests.integration.test_agent_loop -v         # agent loop
PYTHONPATH=src python3 -m pytest -q tests/test_stop_conditions.py               # stop conditions
PYTHONPATH=src python3 -m unittest tests.test_run_logger tests.integration.test_run_logger_agent_loop -v
```

No test needs an API key. `tests/integration/test_model_integration.py` uses mocks.

## Demos and Smoke Tests

Run these from the repository root with `PYTHONPATH=src python3 <script>`.

| Script | Shows | Needs API key |
| --- | --- | --- |
| `scripts/member1_types_smoke.py` | Domain types against the 10 evaluation cases | No |
| `scripts/member1_corpus_smoke.py` | Source register and retrieval | No |
| `scripts/member1_validation_smoke.py` | Parse, validate citations, dispatch | No |
| `scripts/member1_stop_conditions_smoke.py` | The four stop conditions | No |
| `scripts/member2_model_smoke.py` | One live `propose_action` model call (see its `--help`) | **Yes** |
| `scripts/member2_tool_dispatch_demo.py` | Four dispatcher scenarios | No |
| `scripts/member5_approval_demo.py` | Pending, approved once, approval consumed | No |
| `scripts/member5_run_log_demo.py` | Three saved runs, including a human approval pause and resume | No |
| `scripts/show_run_log.py` | Lists saved runs or prints one as a timeline (`--last`) | No |

Human approval uses a second terminal:

```bash
export QA_AGENT_DATA_DIR="$PWD/data/member5-demo" QA_AGENT_APPROVERS="Alice,Bob"
PYTHONPATH=src python3 scripts/approve_cli.py list
PYTHONPATH=src python3 scripts/approve_cli.py approve REQUEST_ID --by Alice --reason "Reviewed."
```

## Runtime Data and Evidence

| Location | Contents | In Git |
| --- | --- | --- |
| `data/` | Approval queue, its lock file, approval audit log | No (`.gitignore`) |
| `evidence/traces/runs/` | One `.jsonl` file per agent run plus `index.jsonl` | Yes, after review |
| `evidence/traces/week5-run-*.json` | Week 5 execution traces (M4) | Yes |
| `evidence/screenshots/`, `evidence/demo/` | Test and demo screenshots per week | Yes |

| Variable | Default | Used by |
| --- | --- | --- |
| `MODEL_ENDPOINT`, `MODEL_NAME`, `MODEL_API_KEY`, `MODEL_TIMEOUT_SECONDS`, `MODEL_MAX_TOKENS`, `MODEL_JSON_MODE` | see `.env.example` | `src/config/loader.py` |
| `QA_AGENT_DATA_DIR` | `data` | `scripts/approve_cli.py` |
| `QA_AGENT_APPROVERS` | none (required) | `scripts/approve_cli.py` |
| `QA_AGENT_TRACE_DIR` | `evidence/traces/runs` | `src/observability/run_logger.py` |

## Security Rules

- Never commit `.env`, keys, databases or `.log` files. The pre-commit hook blocks them.
- Never put a real key in code, tests, screenshots, documentation or command history. Rotate any key that leaks.
- Use synthetic or team-owned data only. No production credentials or data.
- Do not bypass the hook with `git commit --no-verify`.
- Review run logs before committing them as evidence.

Details: `docs/requirements/week3/sensitive-data-check.md`.

## Team and Project Management

| Member | Role |
| --- | --- |
| Member 1 | Project/Requirements Lead |
| Member 2 | Application/Integration Lead |
| Member 3 | AI Engineering Lead |
| Member 4 | Quality/Security Lead |
| Member 5 | DevOps/Documentation Lead |

Tasks, owners, deadlines and evidence links are tracked weekly in ClickUp.
Each member's weekly work is linked to repository evidence.

## Documentation Index

| Topic | Location |
| --- | --- |
| Charter, user stories, traceability, audits | `docs/requirements/` |
| Architecture and diagrams | `docs/architecture/` |
| Prompts and model selection | `docs/prompts/` |
| Evaluations (Weeks 2–4) | `docs/evaluation/` |
| Member 2 integration documents | `docs/integration/` |
| Grounding design note | `docs/context/` |
| Approval gate walkthrough | `docs/requirements/week4/member5-approval-gate-explained.md` |
| Run logger | `docs/requirements/week5/member5-run-log.md` |
| Environment setup | `docs/requirements/week2/setup.md` |
| Weekly progress reports | `docs/weekly reports/` |
| AI-assistance records | `docs/ai-assistance credit/` |

## License

Academic project for BSE4104 at Makerere University.
