# Final Engineering Report: Software-Engineering QA Agent (Group J)

## 1. Executive Summary

Over eight weeks (31 August to 23 October 2026), Group J built the
**Software-Engineering QA Agent**. It is an AI-assisted tool that helps a
small development team:
- Compare requirements with source code and existing tests;
- Find gaps in test coverage;
- Propose a test, and run it only after a named person approves it;
- Explain any failure and draft an issue report for a human to review.

The guiding rule, set in Week 1 and kept throughout, is that **the AI
proposes, while code and people decide**. The model is never trusted to
behave on its own. Every proposal must cite real evidence, every risky
action needs human approval, every run is bounded and recorded, and nothing
reaches a live system. The agent cannot merge code, deploy, submit an issue,
read credentials or run arbitrary shell commands.

**How the work was split:** The five members kept the same roles every week
and provided evidence of their weekly submissions via ClickUp: **Member 1,
Amabe Junior Humphrey** (requirements and traceability); **Member 2, Akanga
Andrew** (integration and architecture); **Member 3, Karagwa Ann Treasure**
(AI engineering); **Member 4, Ayan Mustafa Abdirahman** (quality and security
testing); and **Member 5, Wanyana Selina Masembe** (DevOps and
documentation).

**How it was built.** Each week added one layer on top of a tested baseline:
framing, the model, retrieval, tools, the agent loop, memory, evaluation,
and finally release. The test suite grew from 289 tests in Week 5 to **739**
at release. **61 evaluation scenarios** all behave as expected. In Week 8 the
agent completed its first live end-to-end session with Gemini 2.5 Flash.

Sections 2 to 8 describe the problem and each part of the system; Sections
9 and 10 cover quality, results, challenges and reflection.

## 2. Problem Context and Requirements

### 2.1 The problem

In a small team, a developer must reconcile three sources of truth by hand:
requirements and acceptance criteria; the implementation code; and the
tests, test output and failure logs. This work is repetitive and easy to
postpone. A developer may miss an untested public function, write a test
that is not grounded in a requirement, or spend a long time reading a raw
stack trace. Because the work competes with feature delivery, coverage gaps
and regressions can reach review before anyone notices them.

### 2.2 Users and operating context

The primary user is a developer or QA-focused member of a team of about four
to six engineers. A team lead is the secondary user and reviews proposed
tests, execution decisions and draft issues. The system works on one
team-owned repository with requirements, source code, tests and logs. It
assumes no access to production systems or customer data.

### 2.3 Why an AI-assisted approach

The language-heavy steps suit a model: comparing requirement text with code,
spotting boundary conditions, proposing candidate tests and summarising
failures in plain language. The high-consequence steps stay deterministic.
Code, not the model, decides whether a citation was really supplied, whether
a tool is allowed, whether an approval is valid, whether credentials must be
removed and whether the loop must stop. A persuasive model reply can
therefore never become an authorisation.

### 2.4 Requirements

Member 1 wrote twelve user stories with testable acceptance criteria
(Appendix A gives them in full). Each is enforced by a specific part of the
code:

| ID | Requirement (short form) | Enforced by |
| --- | --- | --- |
| US-1 | Propose at least 3 traceable tests per module, or say honestly that fewer are possible | Prompt, planner, citation validation |
| US-2 | List untested public functions as coverage gaps | Prompt, retrieval |
| US-3 | Run only tests a human approved for the session | Approval gate, test allow-list |
| US-4 | Run tests only in the sandbox, with no secrets reachable | Sandbox executor |
| US-5 | Summarise failures in plain language, citing the log line | Prompt, `draft_issue` |
| US-6 | Draft issues; never post them | `draft_issue` (in-memory only) |
| US-7 | Label weakly grounded output as low confidence | Prompt `confidence` field |
| US-8 | Every proposal cites a real requirement or file, or is rejected | Citation validator |
| US-9 | Stop after a bounded number of steps, time or repetition | Stop conditions |
| US-10 | Log every tool call and decision | Run logger, traces |
| US-11 | Refuse merge, deploy, unapproved commands and prompt-disclosure requests, however delivered | Tool registry, prompt, injection flagging |
| US-12 | A newcomer understands the system from the diagram and boundary matrix | Week 1 architecture and AI Boundary Matrix |

### 2.5 Scope, constraints and success criteria

The system covers one QA workflow with four controlled tools. Merging,
deployment, issue submission, credential or production access, arbitrary
shell commands and multi-repository use are out of scope by design. Success
means at least three traceable proposals per module where evidence allows,
no test run outside the sandbox or without approval, readable failure
summaries, and termination within the loop limit.

## 3. System Architecture

The system is a modular Python codebase with command-line scripts. Its
architecture separates retrieval and context, model proposals, deterministic
validation, tool execution, memory and observability. The Week 1 context
diagram and the retrieval, tool-calling and loop diagrams are in Appendix G.

### 3.1 Request and evidence flow

A caller supplies a goal. The task adapter validates the task contract and
checks that the registered tools match the declared ones. The `AgentLoop`
then runs a bounded cycle of sense, plan, validate, act and observe
(Section 7). The sensor retrieves evidence from the local corpus, and the
context builder packages it with exact source paths, removes credentials and
flags hidden instructions. The planner sends the versioned prompt and
context to the model through an HTTPS client. The reply is parsed as a
`ProposalSet` and treated as untrusted data. Citation validation checks every
cited path before the action reaches the dispatcher, which applies the tool
registry, role checks, schema checks and the human approval gate.

### 3.2 Components and responsibilities

| Component | Responsibility | Code |
| --- | --- | --- |
| Corpus and retrieval | Load provenance-tagged material, rank it locally, report absent evidence | `src/ingestion/`, `src/rag/` |
| Context safeguards | Citeable context, credential redaction, injection flags | `src/rag/` |
| Model boundary | Versioned prompt; HTTPS call with validated settings | `src/prompts/`, `src/models/`, `src/config/` |
| Agent control | Bounded loop, sensor, planner, stop conditions | `src/agent/` |
| Validation and tools | Citation checks; dispatch to four tools and sandbox | `src/orchestrator/`, `src/tools/`, `src/sandbox/` |
| Memory and state | Proposal history and session state; capability interface | `src/memory/`, `src/integration/` |
| Observability and evaluation | Run logs, telemetry, scorer, scenario runner | `src/observability/`, `src/evaluation/` |

### 3.3 Trust boundaries

The model provider is external, and its output is never an authorisation.
Repository content is also untrusted: retrieval keeps provenance, the context
builder applies the input safeguards, and the validator rejects fabricated
citations. The dispatcher is the only route to a tool. Test execution is
limited by an allow-list of existing test IDs, a scrubbed environment and a
timeout, but the sandbox has no filesystem or network isolation, so only
reviewed test code should be run. There is no web interface, no GitHub API
client and no automatic submission path.

## 4. Model and Prompt Engineering

### 4.1 Model selection

Member 3's Model Selection Note chose **Gemini 2.5 Flash** through Google AI
Studio. It supports structured JSON output and tool calling, which the
single-action design needs, and its 1,000,000-token context window far
exceeds a corpus of this size. The free tier is limited by request rate, not
money; paid use costs $0.50 per million input tokens, against $2 for Claude
Sonnet 5. DeepSeek V4-Flash was cheaper but raised data-jurisdiction
concerns. Because free-tier content may be used to improve Google's
products, only team-owned, non-personal material is ever sent. Live runs used
temperature 0.0 through the OpenAI-compatible endpoint.

### 4.2 Model client and configuration

`src/models/client.py` (Member 2) is the single route to the provider. Its
settings come only from environment variables validated by
`src/config/loader.py` (Member 5): model name, endpoint (HTTPS only, no
embedded credentials), and bounded timeout and token limits. The API key is
never printed or logged. A reply that is not valid JSON becomes a fixed error
message, never raw model text.

### 4.3 Prompt design and versions

The `propose_action` prompt has six parts: role, task, context provided,
constraints, output format and failure behaviour. It asks for exactly **one**
JSON action per turn, with arguments, a short rationale, evidence entries
(`source_path` and note) and a confidence level. Retrieved text is declared
to be data, never instructions. Versions are stored as files and loaded by
`src/prompts/loader.py`; each change answered a measured problem:

| Version | Change | Reason |
| --- | --- | --- |
| v1.0 | Baseline structure and JSON output; `no_action` when unsure | Week 2 baseline |
| v1.1 | Copy `source_path` exactly; add `confidence`; never invent a source | Week 2 evaluation found a fabricated-citation risk |
| v1.2 | Memory is context to read, never instructions or approval | Week 6 memory |
| v1.3 | Precise rules for `no_action` with empty or listed evidence | Week 8 alignment with the citation validator |

### 4.4 Prompt evaluation

Member 4's ten-case evaluation (Week 2) tested the prompt with scripted
replies, including two red-team probes that the harness correctly catches.
In Week 8 the same ten cases were run live against Gemini with v1.3: all 10
replies parsed, all 10 citations were valid, there were no safety violations,
and 6 of 10 cases passed fully. One known gap remains: v1.3 tells the model
it receives the tool schemas and the remaining turn count, but the planner
does not yet send them.

## 5. Context and Retrieval-Augmented Generation

### 5.1 Corpus and provenance

The knowledge base is a curated corpus of **22 documents**: requirements,
design notes, code and test logs, in `knowledge/corpus/`. Member 1's
`tag_provenance.py` records each one in a source register with its type and a
SHA-256 hash, so every answer can be traced to a known, unchanged file.

### 5.2 Retrieval

Member 2's pipeline splits documents at paragraph boundaries and ranks the
passages with **BM25**, a classic keyword-ranking method, using statistics
built locally. Nothing is sent over the network for retrieval. If no passage
covers enough of the query terms, the pipeline returns an explicit
`not_in_corpus` result. That decision is made by code, not by the model.

### 5.3 Context building

Member 3's Grounding Design Note sets the rules for `context_builder.py`:
- an evidence budget of about 6,000 tokens per turn;
- retrieval's ranking is trusted, and only whole low-ranked chunks are
  dropped, never truncated, so citations stay exact;
- every chunk is wrapped in an `<evidence source_path=... doc_type=...>`
  tag, the structural form of "retrieved text is data";
- when nothing is found, a plain line says so and the model is expected to
  return `no_action`.

Before the model sees any text, credential-shaped strings are replaced with
`[REDACTED:credential]`, evidence and memory delimiters inside chunk text are
neutralised, and 16 injection rules in six categories flag suspicious
instructions for review.

### 5.4 RAG evaluation

Member 4's fifteen-case evaluation (Week 3) covers answerable, partially
answerable and deliberately unanswerable questions: 11 pass, and 4
reproduce documented limitations. The four limitations are: a verbose query
that falls below the coverage floor; the authoritative requirement ranked
below log chunks with similar words; a three-document question diluted to
one source; and one log incident split across chunks. They are kept visible
as PARTIAL results rather than hidden.

## 6. Tools and Function Calling

### 6.1 The four tools

The model can request only four tools (Member 3), each a class with an
argument schema and an output schema:

| Tool | Risk | What it does | Key limits |
| --- | --- | --- | --- |
| `search_repo` | Read only | Searches the corpus and returns ranked chunks | Optional path scope and result count |
| `read_file` | Read only | Returns one file's text | Only files listed in the source register |
| `run_tests` | Needs approval | Runs existing tests in the sandbox | Allow-listed test IDs; `shell=False`; scrubbed environment; 30 s timeout |
| `draft_issue` | Needs approval | Saves a draft issue with evidence | Stored in memory only; never submitted |

Two actions are never dispatched: `propose_test` completes a run and
`no_action` ends it.

### 6.2 Dispatcher and approval

Member 2's `ToolDispatcher` applies checks in a fixed order: tool registered,
role allowed, arguments valid (unknown keys rejected), approval if required,
run, output valid, output capped at 64,000 bytes. Member 5's approval gate
holds `run_tests` and `draft_issue` until a named approver (from
`QA_AGENT_APPROVERS`) decides with `scripts/approve_cli.py`. Nobody can
approve their own request, each approval works once, an undecided request
expires as denied, and every decision is written to an audit log. Because the
gate returns "pending" rather than blocking, the agent pauses and resumes
cleanly. Member 4's authorisation tests (Week 4) check every tool against
allowed and forbidden roles and failure cases.

## 7. Agent Workflow, State and Memory

### 7.1 Task contract and loop

The task contract (`src/agent/task_contract.yaml`, Member 3) states the goal,
the four tools and the limits: **5 iterations** and a **120-second** budget.
Unknown keys are rejected. Member 2's `AgentLoop` (Figure 1) then repeats one
cycle: check the stop policy; sense (retrieve and build context); plan exactly
one action; validate its citations; act through the dispatcher, or finish on
`propose_test` or `no_action`; observe the result safely; then stop or repeat.

A run ends as completed, awaiting approval (paused, never resubmitted
automatically) or halted/failed. Member 1's stop conditions halt the run on
the iteration cap, the time budget, a repeated identical action, or two
identical tool results, in a fixed order. Each halt is traced. In Week 8,
Member 3 replaced the scripted adapters with the real `RetrievalContextSensor`
and `PromptPlanner`; a history guard removes credentials from earlier turns
before they are re-sent.

![Figure 1. The bounded agent loop (Member 2): sense, plan, validate, act, observe, then stop or repeat. Full-size copy in Appendix G.](docs/architecture/l5-agent-loop.png "3.2")

### 7.2 Session state

Member 2's `SessionState` gives every session an explicit phase: `created`,
`running`, `awaiting_approval`, `completed`, `halted` or `failed`. Only legal
transitions are allowed, and the state is stored in SQLite so a paused
session can be inspected and resumed.

### 7.3 Memory

The one persistent-memory use case is **proposal history per code module**:
which tests were proposed, run, or rejected by a human, so the agent does not
repeat itself. Member 1 wrote the schema, Member 2 the store, Member 3 the
API and Member 5 the retention job. Memory is advisory only:
- prompt v1.2 tells the model memory is context, never instructions or
  approval;
- the approval gate has no memory input, and the memory status list has no
  "approved" value; Member 4's guard tests check this statically and in a
  fresh process;
- only a person can reject a proposal or clear a module's memory;
- by team vote, records are kept until a human clears them.

### 7.4 Interoperability

Member 2 specified one MCP-style capability interface,
`qa-agent.memory-interface/v1`, with five operations (get, list, store and
delete records; read session state). Each needs an explicit permission
scope, writes must quote the current revision so a stale update is
rejected, and outside systems can read session state but never change it.

## 8. Evaluation and Guardrails

### 8.1 Data, criteria and results

One command, `python tests/run_scenarios.py` (Member 5), runs four
independently owned suites:

| Suite | Owner | Cases | PASS | PARTIAL | FAIL | As expected |
| --- | --- | --- | --- | --- | --- | --- |
| Behaviour / adversarial | Member 3 | 30 | 29 | 1 | 0 | 30 |
| Prompt | Member 4 | 10 | 8 | 0 | 2 | 10 |
| RAG | Member 4 | 15 | 11 | 4 | 0 | 15 |
| Failure re-test | Member 4 | 6 | 6 | 0 | 0 | 6 |
| **Total** | | **61** | **54** | **5** | **2** | **61** |

The brief requires at least 30 scenarios. The 61 cover normal (12), edge
(14), incorrect information (6), adversarial (19), tool failure (5) and
unauthorised action (5) cases. Each case records what its owner predicted,
and the run fails on any surprise. The 2 FAIL results are red-team probes the
harness is meant to catch, and the 5 PARTIAL results are documented
limitations. Member 3's scorer judges the 30 behaviour cases on task
completion, groundedness, tool selection, instruction following, safety and
stop reason: all pass except one instruction-following case, the known gap
of unchecked claims in drafts (risk R10). There were 0 safety violations.

### 8.2 Guardrails

The implemented guardrails are: citation validation before dispatch; a role
check before arguments, approval and execution; independent, single-use human
approval that expires to denied; four stop conditions checked before every
turn; memory that can never count as approval; credential redaction and
injection flagging before the model; and fail-closed logging, which stops a
run whose trace cannot be written.

### 8.3 Genuine failures, remediation and re-tests

Member 4's Failure Catalogue documents six genuine defects (the brief
requires five). Each was reproduced against the historical code from Git,
fixed and re-tested against current code, giving 18 history-verified checks:

| ID | Failure | Fix |
| --- | --- | --- |
| F01 | A registered traversal path read outside the corpus | `1a87213` |
| F02 | A stored memory title forged a human rejection line | `c24a5c8` |
| F03 | An authorised requester could approve their own action | `3f121b7` |
| F04 | An unauthorised decision destroyed a pending request | `3f121b7` |
| F05 | A summary-reading telemetry sink deadlocked | `8fa18d6` |
| F06 | Injection and credential flags never reached the trace | `dcf470f` |

F06 was found in the Week 8 hardening pass: detection worked, but no record a
human could read showed that a chunk had been flagged. The loop now records a
flag entry with counts and rule IDs only, never the flagged text.

### 8.4 Traces and observability

Every session writes one trace entry per event (start, context sensed,
injection flagged, action planned, tool dispatched, and the final outcome).
Each entry records the session, the actor (AI, deterministic or human),
enums and counts, and a timestamp, never raw model output or secrets.
Member 5's run logger saves them to `evidence/traces/runs/`, Member 2's
telemetry records step timing and tokens, and Member 4's three example traces
show a completion, a failure with recovery, and a stop-condition halt
(Appendix E).

## 9. Software Engineering Quality and Deployment

Quality practices were added in the same week as each capability, never left
to the end (Section 10.1).

### 9.1 Testing

Everything runs offline, with no API key, in about 12 seconds.
`python -m pytest -q` runs **739 tests**, all passing; the suite grew from 289
tests (Week 5) to 446 (Week 6), 670 (Week 7) and 739 (Week 8). Every
safeguard listed in Section 8.2 has a test that fails if it is removed.

### 9.2 Configuration and secrets

**Configuration (Week 2):** it comes only from validated environment
variables. A missing value stops the program with a message that names the
variable but never shows its value; `.env` is git-ignored. **Commit scanning
(Week 3):** the pre-commit scanner blocks keys, tokens, passwords, personal
identifiers, `.env`, `.log` and database files. **Runtime redaction (Weeks 5
and 8):** the run logger, context builder and history guard remove
credential-shaped strings before any log or model sees them.

### 9.3 Code quality

**Ownership and interfaces:** each package under `src/` has one owner and
one job, and components meet through small, injected interfaces, so each
member could build and test a part in their own week. **Safe failure:**
errors become fixed, sanitised messages, data classes are frozen, and every
proposal is schema-checked. **Reviewed history:** work was merged through
**68 pull requests**, and every member kept a weekly AI Engineering Log
(Appendix F).

### 9.4 CI, reproducibility and deployment

**CI:** `.github/workflows/ci.yml` (Week 8) runs the tests, the scenarios
and the secret scan on every push; in Weeks 2 to 7 the same commands were run
by hand and evidenced with screenshots. **Reproducibility:** dependencies are
pinned in `requirements.txt`, the README and `docs/SYSTEM_GUIDE.md` give
every run command, and every evidence file can be regenerated.
**Deployment:** the system is deliberately a local command-line tool, with no
server, web interface, GitHub write access or production access. **Final
review:** a Week 8 QA review fixed eight infrastructure bugs, each with a
test; for example, the API key appeared when the settings were printed, and
the secret scanner "passed" files it could not find.

## 10. Results, Challenges, Limitations and Professional Reflection

### 10.1 What the group did, from the beginning

The project ran in four phases: **framing** (Week 1), the **AI foundation**
of model, prompts and retrieval (Weeks 2 to 3), **the agent** with tools,
approval, the bounded loop and memory (Weeks 4 to 6), and **prove and
release** with evaluation, live runs, hardening and this report (Weeks 7 to
8). Each member's contribution per week:

| Week | Focus | What the team delivered | Result |
| --- | --- | --- | --- |
| 1 | Problem framing | Charter and 12 user stories (M1); architecture diagram (M2); AI role (M3); AI Boundary Matrix and risk register (M4); GitHub and ClickUp (M5) | A bounded use case: the AI proposes; code and people decide |
| 2 | Model and prompting | Domain types (M1); Gemini client (M2); model choice, prompts v1.0–v1.1 and loader (M3); 10-case evaluation (M4); configuration loader (M5) | A tested baseline; 2 red-team probes caught as intended |
| 3 | RAG | 22-document corpus with provenance (M1); BM25 retrieval (M2); evidence wrapper (M3); 15-case evaluation (M4); secret scanner (M5) | Answers grounded in team documents; 4 retrieval limitations documented |
| 4 | Tools | Citation validation (M1); dispatcher (M2); four tools and sandbox (M3); authorisation tests (M4); human approval gate (M5) | No tool runs without a valid request, an allowed role and, for risky tools, a human "yes" |
| 5 | Bounded agent | Stop conditions (M1); agent loop (M2); task contract (M3); stop tests and 3 traces (M4); run logger (M5) | A multi-step agent that always stops and records every step; 289 tests |
| 6 | Memory and state | Memory schema (M1); store, session state, MCP-style interface (M2); memory API and design note (M3); guard tests (M4); retention and human clear (M5) | Advisory memory, kept until a human clears it; 446 tests |
| 7 | Evaluation and guardrails | Scenario traceability (M1); telemetry (M2); criteria, 30 adversarial cases, scorer (M3); Failure Catalogue (M4); runner for all scenarios (M5) | 61 scenarios, all as expected; 2 real guardrail bugs found and fixed; 670 tests |
| 8 | Hardening and release | Requirements review (M1); release instructions and architecture (M2); real planner and sensor, prompt v1.3, live runs (M3); F06 fix and evaluation evidence (M4); QA review, CI, appendices, deck and report assembly (M5) | First live end-to-end session; 739 tests; release evidence assembled |

### 10.2 Challenges across the eight weeks and how we resolved them

| Week | Challenge | How we resolved it |
| --- | --- | --- |
| 1 | Deciding how much the AI may do alone; telling a model "do not" is not a control | Built the limits into the architecture: schema checks, allow-lists, sandbox, human approval, bounded runs (AI Boundary Matrix) |
| 2 | Scripted test replies could be mistaken for real model behaviour; text in requirements can look like instructions; a model can cite files it was never given | Offline data clearly labelled and live runs reported separately; red-team probes; deterministic citation validation |
| 3 | The secret scanner blocked the `.log` file the RAG evaluation expected; one incident was split across chunks | Used a synthetic `.txt` fixture instead of weakening the scanner; documented fragmentation as a known limitation |
| 4 | Task documents and the repository used different folder names; five members building parts that must fit together | Placed code where it is actually imported; agreed small interfaces so each part was built and tested separately |
| 5 | Tests needed stop conditions that did not exist yet; the pre-commit hook was misnamed, so the secret check had never run; the approval gate blocked, so the loop could not pause; a repository pull erased a member's uncommitted draft | Labelled stand-in replaced by the real policy (identical traces); hook renamed and shown to work; gate returns "pending" with single-use approvals; module rebuilt, and the team committed work earlier |
| 6 | The retention period was undecided while code was written; a memory title could forge a human rejection (F02); some parts had no caller yet | Team vote: keep memory until a human clears it; Member 3 fixed F02 with tests; Member 5 added the `reject-proposal` command |
| 7 | Adversarial cases found two real wrapper-breakout bugs; scenarios were spread over four suites with no combined result | Member 3 fixed both bugs; one runner reports all 61 scenarios and fails on any surprise |
| 8 | Live Gemini obeyed an instruction planted in a source comment; provider rate limits cut live runs short; merge conflicts delayed the release branch; the QA review found eight infrastructure bugs | The flag now reaches the trace (F06), and tool limits plus approval contain the model; live results reported as observations, not rates; Member 2 resolved the conflicts; all eight bugs fixed with tests |

Across all weeks, the hardest part was coordination: each week's work
depended on parts other members were still building. Agreed interfaces,
labelled stand-ins, one branch per task and pull-request review made five
people's work fit together.

### 10.3 What works

Offline, all 61 scenarios behave as expected, with 0 safety violations, and
user stories US-1 to US-11 are each exercised (Section 8). Live, with Gemini
2.5 Flash, an end-to-end session completed in 2 iterations with a grounded
test proposal citing `requirements/authentication.md` and
`src/login_service.py`, and a 10-case trial produced 10 valid citations and 6
full passes (Section 4.4).

### 10.4 What does not work, and remaining risks

- **Flagging does not stop a model:** the planted-instruction case was
  recorded, not blocked; the defence is that the agent cannot act beyond its
  four tools and human approval.
- **Groundedness means citation validity,** not proof that the cited text
  supports the claim; unchecked claims in drafts (risk R10) remain.
- **Thin live evidence:** one live session and two single-shot runs (25
  calls), one stopped by rate limits.
- **Incomplete wiring:** the live planner does not yet read memory or send
  every input prompt v1.3 describes.
- **Containment and detection:** the sandbox is a process, not a container;
  the 120-second budget is a placeholder; regex rules miss paraphrased,
  translated or encoded injections.
- **External dependence** on a hosted model whose availability can change.

### 10.5 Cost and latency

Live calls took **1.8–7.8 s (mean about 4.1 s)** and about **1,450 tokens**
each, so a five-step session takes tens of seconds. The practical limit was
the provider's rate limit, not cost; the recorded token counts allow the
monetary cost to be calculated.

### 10.6 Future work

Repeat each live case several times per prompt version to measure rates;
connect memory to the planner and send every input prompt v1.3 describes;
run tests in a container and check that cited text supports each claim; and
push the release tag and keep CI green.

### 10.7 Professional reflection and human responsibility

**Building in layers worked:** each week added one capability on top of a
tested baseline, and stand-ins let work continue until the real part
arrived. **Visible failures built trust:** red-team probes (Week 2),
documented retrieval limits (Week 3), the Failure Catalogue (Week 7) and a
live injection the model obeyed (Week 8) were reported, not hidden. Overall,
a useful agent is mostly deterministic engineering around one small AI step.

**Humans remain responsible:** a developer sets the goal; a named approver
decides which tests run and which drafts proceed; only a person rejects or
clears memory; and a human reviews every proposal. The team used AI
assistance throughout and owns the result. Every member reviewed, tested and
can explain their code, as their AI Engineering Logs record.
