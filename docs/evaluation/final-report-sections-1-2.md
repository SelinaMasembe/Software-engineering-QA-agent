# Final Engineering Report: Sections 1 and 2

**Project:** Software-Engineering QA Agent  
**Course:** BSE4104 — Emerging Trends in Software Engineering  
**Group:** J  
**Reporting period:** Weeks 1–8, 31 August–20 October 2026

## 1. Executive Summary

Small development teams often have requirements, implementation code, and tests
in separate places. That separation makes it difficult to tell whether a
requirement is implemented, whether an important code path is covered, and
what a failing test means. The Software-Engineering QA Agent addresses this
problem with one bounded workflow: it reads a requirement and its related
repository context, proposes a grounded test, runs only an approved test in a
sandbox, explains failures in plain language, and prepares a draft issue or
pull-request note for human review.

The project deliberately separates AI-assisted reasoning from deterministic
controls. The model proposes actions and test ideas, while application code
validates the response schema and citations, authorizes tools, enforces human
approval, limits execution to the sandbox, redacts credential-shaped content,
records audit traces, and stops the agent when a configured limit is reached.
The agent cannot merge code, deploy, submit an issue, access credentials, or
execute arbitrary shell commands.

Across the completed evaluation work, the project has a 61-scenario evaluation
surface covering normal, edge, adversarial, retrieval, tool-failure, and
historical-regression cases. The Week 8 hardening work also re-tested six
historical failures and closed a traceability gap in the scenario-to-user-story
mapping. The resulting system is appropriate for a small, team-owned
codebase: it improves the speed and consistency of QA analysis without
replacing the human decisions required for consequential repository actions.

## 2. Problem Context

### 2.1 Current problem

In the target setting, a developer or QA-focused team member must manually
reconcile three sources of truth:

1. requirements and acceptance criteria;
2. implementation code and public code paths; and
3. tests, test output, and historical failure logs.

This reconciliation is repetitive and easy to postpone. A developer may miss
an untested public function, write a test that is not grounded in the
requirement, or spend significant time interpreting a raw stack trace before
identifying the likely cause. On a small team, the work competes directly
with feature delivery, so coverage gaps and regressions can reach review
before they are noticed.

### 2.2 Target users and operating context

The primary user is a developer or QA-focused member of a small software team
of roughly four to six engineers. A team or technical lead is the secondary
user and reviews proposed tests, execution decisions, and draft issue content.
The system is designed for one team-owned repository containing a partial
requirements specification, source code, tests, and test logs. It does not
assume access to production systems or confidential customer data.

### 2.3 Why an AI-assisted approach is useful

The language-heavy parts of the workflow are suitable for model assistance:
the agent can compare requirement text with source code, identify likely
boundary conditions, propose candidate tests, and summarise failures in
readable language. These tasks benefit from retrieving and reasoning over
several related documents.

The high-consequence parts remain deterministic. The system, rather than the
model, decides whether a citation was actually supplied, whether a tool is
allowed, whether a human approval is valid, whether a test is inside the
sandbox, whether credentials must be redacted, and whether the loop must stop.
This division reduces the risk that a persuasive model response is treated as
an authorization or execution decision.

### 2.4 Scope and constraints

The implementation covers one end-to-end QA workflow and four controlled tool
roles: repository search, file reading, sandboxed test execution, and draft
issue preparation. The agent loop is bounded by iteration, wall-clock,
repeated-call, and no-new-information conditions. Persistent memory is limited
to module-scoped proposal history, including tests already proposed, run, or
explicitly rejected; previous diagnoses are not reused as evidence.

Automatic merging, deployment, issue submission, pull-request submission,
secret or credential access, production access, arbitrary shell commands, and
multi-repository operation are out of scope. These constraints are central
requirements rather than optional deployment preferences.

### 2.5 Success criteria

The project is evaluated against measurable criteria: at least three
source-traceable test proposals per module when the evidence supports them,
zero test execution outside the sandbox, zero execution of unapproved tests,
human approval for every higher-impact action, readable failure summaries, and
termination within the configured loop limit. The Week 8 traceability
verification also ensures that every evaluation case is either mapped to a
user story or explicitly documented as a contract-level exception.
