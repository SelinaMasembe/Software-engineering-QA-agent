# Week 4 Tool-Schema-to-User-Story Audit

**Module:** BSE4104 — Emerging Trends in Software Engineering
**Deliverable owner:** Member 1 — Project/Requirements Lead
**Week:** Week 4
**Task (Task Allocation Plan):** Check that the tool-related user stories
match the actual tool schemas, and write the code that automatically
rejects a proposal missing a required citation.
**Deliverables:** Updated acceptance criteria (this document plus the
amendment recorded in Section 4 below, applied to
`docs/requirements/Project_charter and user stories.docx`);
`src/orchestrator/validation.py`.

---

## 1. Scope and a repo-structure note

The task sheet names the code deliverable `src/orchestrator/validation.py`.
The repository has no `src/orchestrator/` folder; the module that owns
tool dispatch is `src/orchestrator/` (see `src/orchestrator/__init__.py`
and `src/orchestrator/router.py`, both Member 2's Week 4
deliverable). This mirrors the same task-sheet-versus-repository
discrepancy already resolved for Week 3 (`docs/knowledge/` on the task
sheet versus the repository's actual top-level `knowledge/` folder): the
existing, real folder was used rather than creating a second, unused one.
`validation.py` was therefore added inside `src/orchestrator/`, next to
the dispatcher it validates for.

## 2. What "the actual tool schemas" means here

Four tools are named consistently everywhere in the project: `search_repo`,
`read_file`, `run_tests`, `draft_issue`. Three sources describe them, and
all three were checked against each other and against the twelve user
stories, not just one:

- `src/models/types.py`'s `Action` enum and `src/orchestrator/router.py`'s
  `TOOL_ACTIONS` frozenset — the actual, code-level list of dispatchable
  tools.
- `docs/architecture/Member3_AIEngineering_Deliverables.docx`, "Tool
  Contracts: Draft Schemas for Week 4" — the input/output/authorization
  shape for each of the four tools, written by the AI Engineering Lead
  ahead of Week 4 implementation. This is explicitly labelled "a starting
  point, not a final interface," and no later, Week-4-specific schema
  document from Member 3 exists in the repository yet — implementing and
  registering the four real tools is still an open item (see Section 5).
- `docs/integration/Week4_Member2_ToolCallingOrchestration.docx` — the
  dispatcher's own account of what it does and does not check, and the
  handoffs it expects from other members.

## 3. Story-by-story findings

Of the twelve user stories, eight are tool-related (US-1, US-2, US-3,
US-4, US-5, US-6, US-8, US-11); US-9 and US-10 concern the agent loop and
trace rather than a specific tool's schema, and US-7 and US-12 are not
schema-dependent at all. All eight tool-related stories were checked.

| Story | Finding |
|---|---|
| US-1 | Not schema-specific (concerns `propose_test`, not a dispatched tool). No mismatch. |
| US-2 | Not schema-specific; already flagged in Week 2's traceability notes as an open question for Mustafa (unchanged this week). |
| US-3 | Matches. `run_tests`'s draft schema requires "scope must already be approved for this session," and the dispatcher only calls `run()` on a `REQUIRES_APPROVAL` tool after `ApprovalGate.check()` returns `APPROVED`. Per-test-ID filtering within one approved batch is the concrete `run_tests` tool's responsibility (not yet built), not the dispatcher's; nothing here contradicts the AC. |
| US-4 | Matches at the schema/dispatcher level (`run_tests`'s auth note: "executes only inside the sandbox"). The AC's second sentence, about secrets being unreachable from the sandbox, is a sandbox-runtime property the draft schema does not itself encode; that is expected, since the schema describes the tool's input/output contract, not the sandbox's isolation guarantees, which the Week 1 architecture document's Zone D already covers ("Disposable, network-disabled, credential-free"). No AC change needed. |
| US-5 | Matches. `run_tests`'s draft output (`per_test: [{id, result, duration_ms, stdout, stderr}]`) supplies exactly the raw material (`stdout`/`stderr`) a failure summary would need to cite a specific log line. |
| US-6 | Matches directly. `draft_issue`'s draft output (`{draft_id, status: "draft"}`) and its auth note ("always permitted to draft; posting to GitHub is a separate, explicit human action") match the AC's wording almost exactly. |
| US-8 | **Real, actionable mismatch — see Section 4.** The AC as written only obligates "every proposed test," but the citation requirement in the actual system is broader than that. |
| US-11 | Structurally matches: `TOOL_ACTIONS` only contains `search_repo`, `read_file`, `run_tests`, `draft_issue` — there is no `merge`/`deploy`/arbitrary-command action anywhere in the `Action` enum, so a request for one of those cannot even parse into a known action; it is rejected. One gap noted, not an AC change — see Section 5. |

## 4. Acceptance criteria update (US-8)

**Before:**

> Every proposed test includes a traceable reference (file name/line or
> requirement ID) to the source it was derived from. A proposal without a
> traceable reference to a requirement or code path is rejected
> automatically rather than passed through with a missing citation.

**Why this needed widening:** the AC's own wording ("every proposed
test") scopes the requirement to `propose_test` outputs only. That is
narrower than what the actual system requires and does. `propose_action`
v1.1's OUTPUT FORMAT (`docs/prompts/propose_action/v1.1.md`) requires an
`evidence` field on every response regardless of which of the six actions
is chosen, and Member 2's Week 4 report is explicit that citation
validation is a pre-dispatch boundary check ("Caller must validate before
`dispatch()`"), not a check limited to test proposals. A `search_repo`,
`read_file`, `run_tests`, or `draft_issue` proposal with a fabricated or
missing citation was, before this week, no more blocked than a
`propose_test` one — the code enforcing the rule
(`TestProposal.validate_sources` in `src/models/types.py`, Week 2) was
written against `TestProposal` specifically. `src/orchestrator/validation.py`
closes that gap by checking `ProposalSet.evidence` directly, so the AC
now describes what is actually enforced.

**After (amendment applied to the charter document this week):**

> Every proposed test includes a traceable reference (file name/line or
> requirement ID) to the source it was derived from. A proposal without a
> traceable reference to a requirement or code path is rejected
> automatically rather than passed through with a missing citation. This
> check applies to every dispatched or drafted proposal, not only test
> proposals: propose_action v1.1 requires an evidence field on every
> action, and the Week 4 orchestration boundary validates citations
> before any tool dispatch (search_repo, read_file, run_tests,
> draft_issue), so a proposal with no evidence or a fabricated source_path
> is rejected before it reaches a tool, not only before it becomes a test
> proposal.

This follows the same pattern as Week 2's amendment to US-11 (widening an
AC's wording after finding it did not cover a case the system actually
needed to handle, rather than adding a thirteenth story).

## 5. Gaps noted, no AC change made

- **US-11's "flags the attempt."** The dispatcher's rejection paths for
  an unrecognised or disallowed action (`malformed_request`,
  `unknown_tool`) are, today, ordinary rejections — they do not yet
  produce a distinguishable, logged "flag" tied to
  `BoundaryViolationAttempt` (`src/models/types.py`, US-11's own type).
  The AC's wording is correct as a requirement; the gap is in
  implementation, not documentation, and belongs with the Week 5 agent
  loop / trace work where `TraceEntry` and `BoundaryViolationAttempt` are
  actually wired up. Recorded here so it is not lost, not turned into a
  document edit that would misstate what is already built.
- **Role modelling.** `ToolDispatcher` enforces `context.role in
  allowed_roles` as a hard rejection path (`DispatchCode.UNAUTHORIZED`),
  but the Week 1 architecture document states plainly that "the only
  human role in scope" is the QA engineer/developer — "no reviewer or
  administrator persona is modelled." None of the twelve user stories
  promise role-based tool restrictions, so this is not a mismatch against
  any AC. It is worth the team confirming, when Member 3's real tools are
  registered, that `allowed_roles` is set consistently with that
  single-role model rather than accidentally locking out the one role the
  stories assume.

## 6. Open items to raise with the team

1. Member 3's four tool schemas are still the Week 1 draft version; there
   is no Week 4 update confirming risk level (`READ_ONLY` /
   `REQUIRES_APPROVAL`) or `allowed_roles` for each tool as actually
   registered. This audit used the draft schema and the architecture
   document's role note as the best available ground truth; it should be
   re-checked once Member 3's real tools land, per Member 2's report's
   own open item ("Member 3: implement and register the four real tools
   and their schemas, risks and allowed roles").
2. US-11's "flags the attempt" wording is not yet observable in code
   (Section 5); confirm this is picked up in the Week 5 loop/trace work.
3. Mustafa's confirmation on `edge_stub_implementation` covering both
   US-1 and US-2 is still outstanding from Week 2 and remains open.

## Changelog

- **Week 4:** Initial audit of the eight tool-related user stories
  against the draft tool schemas, the dispatcher implementation, and
  Member 2's Week 4 report. US-8's acceptance criteria widened to cover
  every dispatched or drafted proposal, not only test proposals (Section
  4). Two gaps recorded with no document change (Section 5).
