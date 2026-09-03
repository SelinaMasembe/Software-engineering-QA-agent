# Software-Engineering QA Agent

## Project Overview

The **Software-Engineering QA Agent** is an AI-assisted quality assurance system designed to support software development teams in understanding requirements, proposing relevant tests, executing approved tests in a controlled sandbox environment, analyzing test results, and preparing failure summaries or draft issue/pull-request notes.

The project is being developed as an **AI-native engineering workflow**, where artificial intelligence is used for tasks that require interpretation, reasoning, and analysis, while deterministic software controls permissions, validation, execution, and security boundaries.

The system is intended to assist developers and QA engineers without replacing human responsibility for important engineering decisions.

---

## Problem Statement

Put your work here.

---

## Project Goal

Put your work here.

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

## Initial Architecture

Put your work here.

`docs/architecture/`

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
software-engineering-qa-agent/
│
├── README.md
│
├── docs/
│   ├── requirements/
│   ├── architecture/
│   ├── weekly-reports/
│   ├── evaluation/
│   └── prompts/
│
├── knowledge/
│
├── src/
│
├── tests/
│
├── evidence/
│   ├── traces/
│   └── screenshots/
│
├── demo/
│
└── .env.example
```

### Directory Purpose

| Directory              | Purpose                                                             |
| ---------------------- | ------------------------------------------------------------------- |
| `docs/requirements/`   | Project requirements, charter, user stories and acceptance criteria |
| `docs/architecture/`   | Architecture and system design documentation                        |
| `docs/weekly-reports/` | Weekly progress reports                                             |
| `docs/evaluation/`     | Evaluation plans and results                                        |
| `docs/prompts/`        | Approved prompts and prompt documentation                           |
| `knowledge/`           | Knowledge-base metadata and provenance information                  |
| `src/`                 | Application and agent source code                                   |
| `tests/`               | Automated tests                                                     |
| `evidence/`            | Project evidence, traces and screenshots                            |
| `demo/`                | Demonstration materials                                             |

---

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

## Current Project Status

### Week 1 — Problem Framing and AI-Native Requirements

Current activities include:

- [x] Select Software-Engineering QA Agent use case
- [ ] Complete Project Charter
- [ ] Complete user stories and acceptance criteria
- [ ] Complete AI Boundary Matrix
- [ ] Complete initial architecture/context diagram
- [ ] Create GitHub repository
- [ ] Create ClickUp project
- [ ] Assign Week 1 tasks
- [ ] Collect GitHub and ClickUp evidence
- [ ] Complete Week 1 progress report

The project will be updated as each deliverable is completed.

---

## Future Development

Future project phases will focus on implementing and evaluating the bounded QA workflow.

Potential development areas include:

- Agent implementation
- Approved tool integration
- Sandbox test execution
- Knowledge/context retrieval
- Test-result analysis
- Failure summarisation
- Issue/PR drafting
- Evaluation scenarios
- Security and reliability testing
- Demonstration and final evaluation

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
