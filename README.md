# Software-Engineering QA Agent

## Project Overview

The **Software-Engineering QA Agent** is an AI-assisted quality assurance system designed to support software development teams in understanding requirements, proposing relevant tests, executing approved tests in a controlled sandbox environment, analyzing test results, and preparing failure summaries or draft issue/pull-request notes.

The project is being developed as an **AI-native engineering workflow**, where artificial intelligence is used for tasks that require interpretation, reasoning, and analysis, while deterministic software controls permissions, validation, execution, and security boundaries.

The system is intended to assist developers and QA engineers without replacing human responsibility for important engineering decisions.

---

## Target Users

The primary users of the QA Agent are:

- Software developers
- QA engineers
- Software engineering teams
- Technical project teams working with automated tests

The system is intended to assist these users with test preparation, test-result analysis, and documentation.

---

## Key Capabilities

The QA Agent is expected to support the following capabilities:

1. Read and interpret approved software requirements.
2. Use repository documentation and team-owned project information as context.
3. Identify behaviours that should be tested.
4. Propose relevant test cases.
5. Validate proposed test information against predefined formats and rules.
6. Request or respect human approval before controlled test execution.
7. Run approved tests in a sandbox environment.
8. Inspect test output and logs.
9. Identify and summarize test failures.
10. Draft an issue or pull-request note for human review.

---

## Why Use AI?

AI is appropriate for parts of this workflow because several tasks require interpretation rather than simple fixed rules.

For example, the agent can assist with:

- Understanding natural-language requirements.
- Identifying testable behaviours.
- Generating candidate test cases.
- Connecting test failures with relevant requirements.
- Summarising technical logs.
- Drafting human-readable issue reports.

However, AI will **not** be responsible for unrestricted system control.

Deterministic software and human approval will remain responsible for security-sensitive and potentially destructive actions.

---

## AI and System Responsibilities

| AI Agent                    | Deterministic Software / Human          |
| --------------------------- | --------------------------------------- |
| Interpret requirements      | Enforce permissions                     |
| Identify testable behaviour | Validate data and schemas               |
| Generate test proposals     | Control available tools                 |
| Analyse test output         | Enforce sandbox restrictions            |
| Summarise failures          | Restrict executable commands            |
| Draft issue/PR notes        | Human reviews important actions         |
| Suggest possible causes     | Human makes final engineering decisions |

This separation helps ensure that the AI provides useful reasoning while deterministic controls enforce the project's safety boundaries.

---

## Safety and Security Boundaries

The QA Agent is deliberately restricted.

### The agent MAY:

- Read approved requirements and repository documentation.
- Analyse approved source code and test logs.
- Propose test cases.
- Analyse test results.
- Draft issue or pull-request notes.
- Execute tests that have been explicitly approved and are available within the controlled sandbox.

### The agent MUST NOT:

- Access production systems.
- Deploy software to production.
- Automatically merge pull requests.
- Access or expose secrets.
- Execute arbitrary unrestricted shell commands.
- Directly control infrastructure.
- Make changes outside the approved sandbox.
- Make final engineering or security decisions without appropriate human review.

These boundaries are based on the selected Software-Engineering QA Agent use case and its stated safety requirements.

---

## Project Scope

### In Scope

- Requirement interpretation
- Test-case proposal
- Test planning
- Controlled test execution
- Test-result analysis
- Failure summarisation
- Issue/PR note drafting
- Controlled access to project documentation
- Sandbox-based testing

### Out of Scope

- Production deployment
- Automatic pull-request merging
- Direct infrastructure control
- Secret management
- Autonomous financial or business decisions
- Unrestricted command execution
- Fully autonomous software development

---

## Data Sources

The project will use approved and team-owned information, including:

- Software requirements
- Repository documentation
- Team-owned source code
- Test cases
- Test logs
- Synthetic or controlled project data where required

Sensitive credentials and restricted information will not be committed to this repository.

---

## Repository Structure

```text
Software-engineering-QA-agent/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── docs/
│   ├── architecture/
│   ├── evaluation/
│   ├── integration/
│   ├── prompts/
│   ├── requirements/
│   ├── weekly reports/
│   └── setup.md
├── evidence/
│   ├── demo/
│   ├── screenshots/
│   └── traces/
├── knowledge/
├── scripts/
│   └── member2_model_smoke.py
├── src/
│   ├── config/
│        ├── __init__.py
│        └── loader.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── client.py
│   ├── prompts/
│   │   └── loader.py
│   └── rag/
│       └── pipeline.py
└── tests/
    ├── fixtures/
    ├── integration/
    │   └── test_model_integration.py
    ├── test_config.py
    └── test_prompt_harness.py
```

## Setup

### Requirements

- Python 3.10 or newer
- A Google AI Studio API key
- Internet access for live model requests

### Create the virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt

### Configure local environment variables

Create a local environment file:

```bash
cp .env.example .env
```

Edit `.env` and add the API key. Never commit `.env` or place the key in a command-line argument.

Load the variables into the current terminal session:

```bash
set -a
source .env
set +a
```

Activating `.venv` does not automatically load `.env`.

## Running Tests

### Member 5 configuration tests

```bash
PYTHONPATH=src python3 -m unittest tests.test_config -v
```

### Model integration tests

These tests use mocks and do not contact Google:

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_model_integration -v
```

### Full offline test suite

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The offline suite does not require an API key.

## Running the Live Smoke Test

The smoke test sends one real requirement and source-code example to the configured model:

```bash
set -a
source .env
set +a

PYTHONPATH=src python3 scripts/member2_model_smoke.py \
  --prompt-file docs/prompts/propose_action/v1.0.md \
  --prompt-version v1.0 \
  --requirement-id REQ-AUTH-01 \
  --requirement-file tests/fixtures/member2/login_requirement.txt \
  --source-file tests/fixtures/member2/login_service.py
```

A successful result includes:

- Model name
- Prompt version
- Request latency
- Token usage
- Structured model output

The smoke test proposes an action. It does not create files, execute tests, or modify the repository.

## Configuration Files

| File | Purpose |
|---|---|
| `.env.example` | Safe template showing required environment variables |
| `.env` | Local secrets and settings; never commit |
| `src/config/loader.py` | Loads and validates environment settings |
| `src/config/__init__.py` | Exposes the configuration loader interface |
| `src/models/client.py` | Calls the configured model provider |
| `scripts/member2_model_smoke.py` | Runs one live model interaction |
| `tests/test_config.py` | Tests Member 5 configuration behavior |
| `tests/integration/test_model_integration.py` | Tests model-client and pipeline behavior |

## Troubleshooting

### Missing environment variable

Reload the environment:

```bash
set -a
source .env
set +a
```

## Security Rules

- Never commit `.env`.
- Never place a real API key in source code, screenshots, tests, or command history.
- Revoke any key accidentally exposed in chat, logs, or screenshots.
- Use synthetic or team-owned project data only.
- Do not use production credentials or production data.
- Review model-proposed actions before execution.
- Keep provider errors free from API keys and other secrets.

## Team Roles

The project follows the recommended five-role team structure:

| Role                         | Responsibility                                  |
| ---------------------------- | ----------------------------------------------- |
| Project/Requirements Lead    | Requirements, project charter and user stories  |
| Application/Integration Lead | System architecture and integrations            |
| AI Engineering Lead          | AI workflow, prompts and agent behaviour        |
| Quality/Security Lead        | Testing, security and AI boundaries             |
| DevOps/Documentation Lead    | Repository, ClickUp, evidence and documentation |

The team members will be listed below:

| Team Member | Role                         |
| ----------- | ---------------------------- |
| Member 1    | Project/Requirements Lead    |
| Member 2    | Application/Integration Lead |
| Member 3    | AI Engineering Lead          |
| Member 4    | Quality/Security Lead        |
| Member 5    | DevOps/Documentation Lead    |

---

## Project Management

**ClickUp** is used to manage project tasks, weekly activities, task ownership, deadlines and evidence.

Each weekly activity is assigned to a specific team member to ensure that individual contributions are identifiable.

Repository evidence and relevant deliverables will be linked to the corresponding ClickUp tasks.

---

## Development Principles

The project will follow these principles:

1. **Human oversight** — important or risky actions require appropriate human approval.
2. **Least privilege** — the agent receives only the access required for its task.
3. **Sandbox execution** — approved tests are executed in a controlled environment.
4. **Traceability** — important agent actions and test results should be recorded.
5. **Deterministic controls** — permissions, validation and execution restrictions are enforced outside the language model.
6. **No production access** — the agent will not directly control production systems.
7. **Evidence-based development** — project decisions and evaluation results will be documented.

---

## Safety Notice

This project is an academic/software-engineering prototype.

The QA Agent is designed to operate only within explicitly defined permissions and controlled environments. It is not intended to autonomously control production systems or make irreversible engineering decisions.

---

## Documentation

Project documentation is maintained under:

```text
docs/
```

Evidence is maintained under:

```text
evidence/
```

Weekly progress documentation is maintained under:

```text
docs/weekly-reports/
```

---

## License

This project is developed for academic purposes as part of a university software engineering project.
