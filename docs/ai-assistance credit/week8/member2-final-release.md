# AI Engineering Log — Week 8 Member 2 Final Release

## Scope

I used AI assistance for my Week 8 Member 2 work: the tagged release
`v1.0.0`, the README run instructions, the architecture diagram update, final
report Section 3 (System Architecture) in
`docs/integration/week8-member2-system-architecture.md`, and updating
`docs/architecture/QA_Agent_Architecture_Week1.docx` so that the whole document
describes the implemented Week 8 system.

## Model and Tool

| Model | Tool | Used for |
| --- | --- | --- |
| GPT-6 Luna | OpenAI Codex | Reading the assignment and Team Task Allocation Plan, planning the Week 8 milestones, aligning the architecture docs with the code, writing the run instructions, drafting Section 3 and running the release checks. |
| Claude Opus 5.5 | Antigravity | Final release review: checking the work against my Week 8 row, merging the team's newer Week 8 work from `main`, updating Section 3 of `docs/architecture/QA_Agent_Architecture_Week1.docx` in place, and rerunning the release checks. |
| Claude Opus 5.5 | Claude Code | Finishing the architecture document: updating its other sections, redrawing the container diagram, and fixing the caption numbers and contents pages. Rebuilding my branch as incremental commits on top of `main`, and rerunning the release checks. |

As in Week 7, I had the agent read my earlier Codex session history first, so
it followed the same workflow, file layout and ownership boundaries.

## How I Used It

I asked the AI for my Week 8 tasks as Member 2. My row in the Team Task
Allocation Plan says: prepare the final tagged release with run instructions,
and write the System Architecture section of the report. I agreed a plan of
milestones and gates with the agent, then let it implement each milestone and
checked each gate before it moved on. I asked for incremental commits on the
`week8-member2-final-release` branch.

| Milestone | What I had the agent implement | Gate check I ran | Commit |
| --- | --- | --- | --- |
| M1 Architecture alignment | README architecture table and Draw.io diagram matched to the code (prompt v1.1 → v1.3, sandbox wording, injected sensor and planner) | Each component and path checked against `src/`; diagram XML parses | `0118031` |
| M2 Section 3 draft | `docs/integration/week8-member2-system-architecture.md` | Every claim traced to a module; limits stated (no filesystem or network isolation in the test subprocess) | `5b7d870` |
| M3 Run instructions | "Run the Tagged Release" steps and the observability demo row in the README | Commands run from the repository root without an API key | `dd3f198` |
| M4 Release review | Brought my branch up to date with the team's latest `main` (Member 4's Week 8 guardrail fix and evidence) and updated the README and Section 3 draft to match | Full suite, all scenarios, demo and sensitive-data scan pass on the updated branch | `699cb6b` |
| M5 Architecture document | Updated `docs/architecture/QA_Agent_Architecture_Week1.docx` in place, instead of keeping a separate Week 8 report: purpose and scope, principles, system context, a redrawn container view and trust-zone table, and the out-of-scope list | Each statement checked against `src/`; rendered document checked page by page; caption numbers and contents page numbers correct | `55f18a3` |

## Examples

- **Scope.** I told the agent to do only Member 2's work. It left the other
  members' report sections, fixes, evidence pack and presentation alone.
- **Stale prompt version.** The agent found that the README architecture table
  still named prompt v1.1 while the current prompt is v1.3, and I had it
  corrected before writing Section 3.
- **Honest limits.** I required Section 3 to say that the test executor is an
  allow-listed subprocess with a stripped environment and a timeout, and that
  it does not isolate the filesystem or network.
- **Tag on an integrated commit.** In the review I found that `main` had moved
  after the first tag: Member 4 had merged the fix that records injection and
  credential flags in the agent trace, and the scenario count went from 60 to
  61. I brought my branch up to date with `main`, updated Section 3 and the
  README numbers, and moved the local `v1.0.0` tag to the final commit.
- **Whole architecture document.** When I checked
  `QA_Agent_Architecture_Week1.docx`, only Section 3 had changed. The other
  sections still described the Week 1 design: a browser client, a disposable
  network-disabled sandbox, a GitHub write zone, and a `full-spec.md` file that
  does not exist. I had the agent update every section to match the code and
  redraw the container view. It also fixed the captions, which showed heading
  text instead of section numbers (for example "Table System context.2").
- **Clean history.** Before pushing, I had the agent rebuild my branch on top
  of `main` as incremental commits, without the merge commit and without the
  separate Week 8 report I had decided not to keep. The final files are the
  same as before the rebuild.
- **Commits.** I asked for commit messages that do not mention Claude, Codex or
  AI.

## Verification

Results on the release commit:

- Full pytest suite: 676 passed, 625 subtests passed, 6 collection warnings
  (for domain classes named `TestProposal` and `TestOutcome`).
- `tests/run_scenarios.py --no-write`: 61 scenarios, PASS 54, PARTIAL 5,
  FAIL 2; all 61 behaved as their owners expect.
- `scripts/member2_observability_demo.py --no-write` ran as written in the
  README.
- `scripts/check_sensitive.py --all` exited 0.

No API keys, credentials, confidential data or personal data were sent to
either model. All checks ran offline. I remain responsible for the submitted
release and documentation.
