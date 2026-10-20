# Final Engineering Report, Section 8: Evaluation, Observability and Guardrails

**Author:** Member 4 (Quality/Security Lead). **Date:** 20 October 2026.
**Scope per the brief's report template (1.5-2 pages):** evaluation
data/criteria/results, genuine failures, traces/logs, guardrails,
remediation and re-test evidence.

## 8.1 Evaluation data, criteria and results

The evaluation suite runs through one entry point,
[`tests/run_scenarios.py`](../../tests/run_scenarios.py) (Member 5), which
combines four independently-owned suites into one report rather than
re-implementing any of them:

| Suite | Owner | Cases | What it exercises |
| --- | --- | --- | --- |
| `behaviour` | Member 3, Week 7 | 30 | The real `AgentLoop`, `ToolDispatcher`, `JSONApprovalGate` and sandbox, scored by `src/evaluation/scorer.py` |
| `prompt` | Member 4, Week 2 | 10 | `propose_action` against scripted model responses |
| `rag` | Member 4, Week 3 | 15 | Real retrieval: answerable, partially-answerable and deliberately-unanswerable questions |
| `failure_retest` | Member 4, Weeks 7-8 | 6 | Historical regression reproduction (below) |

**Total: 61 scenarios** (the brief requires at least 30), covering normal,
edge, failure and adversarial cases. The latest run
([`evidence/evaluation/week7-scenario-results.md`](week7-scenario-results.md),
regenerated 20 October 2026 at commit `92fe86f`): **54 PASS, 5 PARTIAL, 2
FAIL — 61 of 61 behaved exactly as their owner expected.** A PARTIAL or FAIL
here is never a silent regression: every case records what its owner
predicted, and the run only succeeds when the observed outcome matches that
prediction. The 2 FAIL and 5 PARTIAL cases are deliberate red-team probes
and documented known limitations (for example, the RAG suite's verbose-query
coverage-floor false negative, `docs/evaluation/week3-fifteen-case-rag-evaluation.md`),
not bugs.

`behaviour`'s criteria, from `src/evaluation/scorer.py` (Member 3): task
completion (the expected end state was reached), groundedness (every
rejected proposal matches the expected rejection count and the final
proposal's citations were actually supplied that turn), tool selection
(only allowed tools ran, and every required tool ran), instruction
following (confidence, forbidden text, and whether an attack attempt was
correctly flagged), and safety violation (no action that must never execute
did, no forbidden text or credential-shaped string reached the model, and
the evidence wrapper stayed intact).

Two live calls against a real model (Gemini 2.5 Flash) are recorded under
`evidence/test-runs/week8/real-model/`, confirming the scripted-response
evaluation above reflects genuine model behaviour and not only a fixture.

## 8.2 Guardrails implemented

- **Citation validation** (`orchestrator/validation.py`): every proposal's
  evidence is checked against what was actually supplied that turn before
  anything is dispatched; an untraceable citation is rejected, never
  executed.
- **Tool authorization** (`orchestrator/router.py`): a per-tool
  `allowed_roles` check runs before argument validation, before the
  approval gate, and before `run()`.
- **Human approval** (`orchestrator/approval_gate.py`): `run_tests` and
  `draft_issue` require an explicit, independently-authorized human
  decision; self-approval and unauthorized decisions are refused without
  corrupting the pending request (F03, F04 below); a request nobody decides
  expires to DENIED, never to APPROVED.
- **Bounded stop conditions** (`agent/stop_conditions.py`, US-9): iteration
  cap, wall-clock budget, repeated-call detection and no-new-information,
  checked in a fixed precedence before every turn and after every
  observation.
- **Memory/approval isolation** (`tests/test_memory_guard.py`, Week 6): the
  approval gate's protocol has no memory-shaped parameter, memory's own
  status enum has no "approved" value, and `src/agent`/`src/tools` never
  import `memory.api` — verified both statically (AST) and dynamically (a
  fresh-process import check), not just documented.
- **Credential redaction** (`rag/credential_scan.py`, R4): credential-shaped
  strings are replaced with `[REDACTED:credential]` before any chunk
  reaches the model.
- **Injection flagging** (`rag/injection_flagging.py`, R1): content
  resembling an embedded instruction is flagged, never removed, so a human
  can review it. **This guardrail had a wiring gap closed in Week 8 — see
  F06.**

## 8.3 Genuine failures, remediation and re-test evidence

[`docs/evaluation/week7-failure-catalogue.md`](week7-failure-catalogue.md)
documents **six** genuine defects (the brief requires at least five), each
reproduced against the exact historical module from Git, fixed, and
re-tested against current code — **18 history-verified checks in total**,
evidence at
[`evidence/evaluation/week8-failure-retest.json`](../../evidence/evaluation/week8-failure-retest.json).

| ID | Failure | Fix |
| --- | --- | --- |
| F01 | A registered traversal path read outside the corpus | `1a87213` |
| F02 | A stored memory title forged a human rejection line | `c24a5c8` |
| F03 | An authorized requester could approve their own action | `3f121b7` |
| F04 | An unauthorized decision destroyed a pending request | `3f121b7` |
| F05 | A summary-reading telemetry sink deadlocked | `8fa18d6` |
| F06 | A flagged chunk's injection/credential flags never reached the trace | `dcf470f` |

**F06 is this section's own contribution**, found during the Week 8
hardening pass rather than pulled from project history: `AssembledContext`
correctly carried `.flagged` out of `build_context`, but `AgentLoop` never
read it, and `injection_flagging.flag_trace_entry` — written specifically
to turn a flag into a trace entry — was called only by its own tests. Risk
R1 promises content is "flagged during ingestion for review"; detection
worked, but nothing a human could read ever recorded that a chunk had been
flagged, so the review half of that promise was not actually happening in a
real session. The fix (`dcf470f`) has `AgentLoop` record the flag entry
through the same fail-closed trace-sink path every other trace entry uses,
whenever a turn's context carries one. Re-tested six ways:
`tests/test_failure_retest.py::test_F06_flagged_chunk_reaches_the_trace`
(historical reproduction) plus five additional cases in
`tests/test_loop_injection_trace.py` against current code — an unflagged
turn stays silent, multiple flagged chunks combine into one entry, the
entry never carries the flagged chunk's text, and a trace-sink failure on
this entry still fails the loop closed, the same as any other trace write.

## 8.4 Traces and logs

Every `AgentLoop` session produces one `TraceEntry` per lifecycle event
(`loop_started`, `context_sensed`, `injection_flagged` when applicable,
`action_planned`, `tool_dispatched`, `loop_completed`/`loop_halted`/`loop_failed`),
each carrying a session ID, actor (AI/deterministic/human), a fixed-vocabulary
detail string built only from enums and counts — never raw exception text
or model output — and a timestamp. Three example sessions are captured
under `evidence/traces/` (a clean completion, a tool failure followed by
recovery, and a stop-condition halt), and `evidence/traces/runs/` holds
further JSONL run logs from `src/observability/run_logger.py` (Member 5).
`src/observability/telemetry.py` (Member 5) separately records step-level
timing (sense/plan/act/observe) for performance observability; F05 above is
a genuine deadlock this module had and no longer has.

## 8.5 Remaining limitations

The RAG pipeline's lexical retrieval has four documented, reproducible
grounding limitations (Week 3) that remain limitations, not failures, by
design — they describe the current retrieval policy's edges, not a defect
to fix before submission. The injection-flagging and credential-scanning
rules are regex-based, deliberately narrow, and documented as a first line
of defence, not a classifier: a paraphrase, another language, or an encoded
payload is not detected, and flags are for review, never used to drop
content. Both are explicit, tested known limits, not silent gaps.
