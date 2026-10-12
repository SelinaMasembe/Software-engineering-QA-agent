# AI Engineering Log — Week 7 Member 2 Observability

## Scope

I used AI assistance to build the Week 7 Member 2 logging system: the step
telemetry recorder, the wrappers that record the agent's model, retrieval,
tool and timing evidence, their tests, the offline demonstration and
evidence, and the deliverable document
`docs/integration/Week7_Member2_Observability.docx`.

## Model and Tool

| Model | Tool | Used for |
| --- | --- | --- |
| Claude Opus 5.5 (`claude-opus-5-5`) | Claude Code | Reading the assignment, allocation plan and earlier Codex sessions; implementing each milestone; writing tests; generating the demonstration evidence and the Word deliverable. |

Earlier Member 2 weeks used OpenAI Codex and Claude Code. Their session
history was read at the start of Week 7 so the same workflow, file layout and
ownership boundaries were followed.

## How I Used It

I asked the AI for the work I had to do specifically as Member 2. Then I
created the gates and milestones and let the agent implement them, while I
tested at each gate and milestone to make sure it was doing the correct thing.

A milestone was one reviewable increment. A gate was the set of checks that
had to pass before the next milestone started. Each passed milestone was
committed separately on the `week7-observability-logging` branch.

| Milestone | What the agent implemented | Gate check | Commit |
| --- | --- | --- | --- |
| M1 Core recorder | `src/observability/telemetry.py` and unit tests | Unit tests pass; sensitive-data scan clean | `2b0205b` |
| M2 Instrumentation | `src/observability/instrumentation.py` and 16 integration tests | Same loop result and trace entries with and without wrappers; whole suite passes; three deliberate defects caught | `2624783`, `7a1da33` |
| M3 Demonstration | `scripts/member2_observability_demo.py` and evidence files | All three scenarios reach the expected outcome; evidence passes the sensitive-data scan | `4b3d22d`, `1e2a832` |
| Review gate | Sink writes moved outside the recorder lock | Deadlock reproduced on the old code; all 30 tests pass after the fix | `8fa18d6` |
| M4 Report and log | Word deliverable, its generator and this log | Report figures checked against test output and the committed evidence | Final commits |

## Examples

- **Scope.** I asked the agent to respect the work boundaries and do only
  Member 2's work. It took Member 2's row from the Team Task Allocation Plan
  and did not touch Member 1's coverage script, Member 3's scorer, Member 4's
  Failure Catalogue or Member 5's scenario runner.
- **Path decision.** The plan names `src/logging/observability.py`. The agent
  reported that a `src/logging` package would shadow Python's standard
  `logging` module and proposed `src/observability/`, which Member 5 already
  used for the same reason in Week 5. The decision is recorded in Section 3
  of the report.
- **Gate 2 failures.** Three integration tests failed on the first run because
  the fixture corpus also returned its test-log file and a shortened goal
  found no evidence. The test expectations were corrected to match real
  retrieval; the code did not change.
- **Review gate defect.** Sinks were written while the recorder lock was held,
  so a sink that read the summary would deadlock. A new test reproduced the
  hang on the old code before the fix was accepted.
- **Rejected option.** Recording the source paths the model cites verbatim was
  rejected because model output is untrusted. Paths outside the turn's allowed
  set are counted instead of copied.
- **Branch and commits.** I asked for a branch name without "claude" or "ai"
  and for incremental commits.

## Design Decisions

- The agent loop, dispatcher, retrieval, model client, stop policy and
  Member 5's `RunLogger` are wrapped, never edited.
- Wrappers return the same result and re-raise the same exception, so the loop
  reaches the same outcome with or without telemetry.
- A telemetry write failure is counted, never raised; the fail-closed audit
  trail stays with Member 5's `RunLogger`.
- Records are metadata only: no prompt text, retrieved text, argument values,
  output values or exception messages.

## Verification

- 30 Member 2 observability tests passed (14 unit, 16 integration).
- The whole suite passed: 444 tests and 267 subtests (414 before this work).
- The README command `unittest discover -s tests` ran 229 tests, OK.
- The demonstration reached the expected outcome in all three scenarios.
- `scripts/check_sensitive.py` reported no findings on the new files.
- The Word document was rendered and every page was checked.

No API keys, credentials, confidential data or personal data were sent to the
model. The demonstration uses the team's fixture corpus and an offline model
adapter. I remain responsible for the submitted code and documentation.
