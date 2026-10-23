# ClickUp Board Completion Checklist

BSE4104 Software-Engineering QA Agent | Group J | Prepared by Member 5, 23 October 2026.

The brief's Week 8 deliverables include a "completed ClickUp board and final
repository evidence". ClickUp is updated by hand.

Members: **M1** Amabe Junior Humphrey (Requirements), **M2** Akanga Andrew
(Integration), **M3** Karagwa Ann Treasure (AI Engineering), **M4** Ayan Mustafa
Abdirahman (Quality/Security), **M5** Wanyana Selina Masembe (DevOps/Docs).

---

## Week 1: Problem framing (31 Aug – 4 Sep)

- [X] **M1** Project Charter and 12 user stories: `docs/requirements/Project_charter and user stories.docx`
- [X] **M2** Initial architecture diagram: `docs/architecture/system-achitectue.jpeg`
- [X] **M3** AI role and value justification: `docs/architecture/Member3_AIEngineering_Deliverables.docx`
- [X] **M4** AI Boundary Matrix and story review: `docs/requirements/week1/quality-and-security-documentation.docx`
- [X] **M5** GitHub repo, ClickUp board, Week 1 report: `evidence/screenshots/week1/`, `docs/weekly reports/WEEK 1 PROGRESS REPORT.docx`

## Week 2: Foundation model and prompting (7 – 11 Sep)

- [X] **M1** Traceability notes and data types: `docs/requirements/week2-test-case-traceability.md`, `src/models/types.py`
- [X] **M2** Model client: `src/models/client.py`, `docs/integration/week2-member2-model-integration.md`
- [X] **M3** Model Selection Note, Prompt Specification, prompt loader: `docs/prompts/`, `src/prompts/loader.py`
- [X] **M4** Ten-case prompt evaluation: `docs/evaluation/week2-ten-case-evaluation.md`, `tests/test_prompt_harness.py`
- [X] **M5** Environment config loader and Week 2 report: `src/config/loader.py`, `.env.example`, `docs/weekly reports/WEEK 2 PROGRESS REPORT.docx`

## Week 3: Context and RAG (14 – 18 Sep)

- [X] **M1** Corpus and Source Register: `knowledge/source-register.md`, `src/ingestion/tag_provenance.py`
- [X] **M2** Retrieval pipeline and diagram: `src/rag/`, `docs/architecture/l3-retrieval-pipeline.png`
- [X] **M3** Grounding note and context builder: `docs/context/Grounding_Design_Note.docx`, `src/rag/context_builder.py`
- [X] **M4** Fifteen-case RAG evaluation: `docs/evaluation/week3-fifteen-case-rag-evaluation.md`, `tests/test_rag_eval.py`
- [X] **M5** Pre-commit sensitive-data check and Week 3 report: `scripts/check_sensitive.py`, `.githooks/pre-commit`, `docs/weekly reports/WEEK 3 GROUP PROGRESS REPORT.docx`

## Week 4: Tools and function calling (21 – 25 Sep)

- [X] **M1** Tool-story audit and citation validation: `docs/requirements/week4/week4-tool-schema-user-story-audit.md`, `src/orchestrator/validation.py`
- [X] **M2** Tool dispatcher and diagram: `src/orchestrator/router.py`, `docs/architecture/l4-tool-calling.png`
- [X] **M3** Four tools: `src/tools/`
- [X] **M4** Tool authorization tests: `tests/test_tool_auth.py`, `docs/evaluation/week4-tool-authorization-evaluation.md`
- [X] **M5** Human approval gate and Week 4 report: `src/orchestrator/approval_gate.py`, `scripts/approve_cli.py`, `docs/weekly reports/WEEK 4 GROUP J PROGRESS REPORT.docx`

## Week 5: Bounded agent (28 Sep – 2 Oct)

- [X] **M1** Charter check and stop conditions: `docs/requirements/week5/week5-task-contract-charter-audit.md`, `src/agent/stop_conditions.py`
- [X] **M2** Agent loop and diagram: `src/agent/loop.py`, `docs/architecture/l5-agent-loop.png`
- [X] **M3** Agent Task Contract: `src/agent/task_contract.yaml`
- [X] **M4** Three execution traces and stop-condition tests: `evidence/traces/`, `tests/test_stop_conditions.py`
- [X] **M5** Run logger and Week 5 report: `src/observability/run_logger.py`, `evidence/traces/runs/`, `docs/weekly reports/WEEK 5 GROUP J PROGRESS REPORT.docx`

## Week 6: Memory, state and interoperability (5 – 9 Oct)

- [X] **M1** Memory description and schema: `docs/requirements/week6/week6-memory-description-audit.md`, `src/memory/schema.py`
- [X] **M2** Memory store, state model, MCP interface: `src/memory/store.py`, `src/integration/mcp_interface.py`, `docs/integration/week6-member2-mcp-interface.md`
- [X] **M3** Memory Design note and memory API: `docs/requirements/week6/memory-design-and-data-handling-note.md`, `src/memory/api.py`
- [X] **M4** Memory security review and guard tests: `tests/test_memory_guard.py`
- [X] **M5** Retention job and Week 6 report: `src/memory/retention.py`, `docs/weekly reports/WEEK 6 GROUP J PROGRESS REPORT.docx`

## Week 7: Evaluation, observability and guardrails (12 – 16 Oct)

- [X] **M1** Scenario traceability: `tests/test_scenario_coverage.py`
- [X] **M2** Observability logging: `src/observability/telemetry.py`, `instrumentation.py`, `evidence/traces/observability/`
- [X] **M3** Evaluation criteria, adversarial cases, scorer: `docs/evaluation/AI_Behaviour_Evaluation_Criteria.docx`, `tests/adversarial/fixtures.py`, `src/evaluation/scorer.py`
- [X] **M4** Failure Catalogue and re-tests: `docs/evaluation/week7-failure-catalogue.md`, `tests/test_failure_retest.py`
- [X] **M5** Scenario runner and Week 7 report: `tests/run_scenarios.py`, `evidence/evaluation/week7-scenario-results.md`, `docs/weekly reports/WEEK 7 GROUP J PROGRESS REPORT.docx`

## Week 8: Release, report and demonstration (19 – 23 Oct)

- [X] **M1** Requirements review and report §1–2: `docs/evaluation/final-report-sections-1-2.md`
- [X] **M2** Tagged release, README run instructions, report §3: `README.md`, `docs/integration/week8-member2-system-architecture.md`. **Open: push the `v1.0.0` tag.**
- [X] **M3** Bug fixes and report §4, §6, §7: `src/agent/planner.py`, `src/agent/sensor.py`, `docs/prompts/propose_action/v1.3.md`. **Open: §4, §6, §7 not yet committed.**
- [X] **M4** Evidence pack, guardrail fix, report §8: `docs/evaluation/final-report-section8-evaluation-guardrails.md`, `evidence/evaluation/week8-failure-retest.json`
- [X] **M5** Infrastructure fixes, appendices, ClickUp and repo evidence, presentation, report §9–10: `docs/final-report/`, `docs/presentation/`, `docs/SYSTEM_GUIDE.md`
- [X] **Team** Report §5 (Context and RAG): **Open; no owner in the plan.**
