# AI Engineering Log — Week 4 Member 2 Tool Calling

## Scope

I used AI assistance while implementing the single-turn tool-dispatch layer,
its focused tests, offline demonstration, architecture page and deliverable
guide.

## Tools and Material Contributions

| Tool | Contribution |
| --- | --- |
| OpenAI Codex | Analysed the assignment and repository, defined ownership boundaries, implemented and verified the dispatcher, reviewed generated material, exported the diagram, and maintained incremental commits. |
| Claude Code | Independently reviewed the plan and dispatcher, identified fail-closed edge cases, drafted dispatcher tests, drafted the offline demo, drafted the L4 Draw.io page, and drafted the first-person guide. |

## Decisions I Reviewed and Accepted

- One proposal produces one `DispatchResult`; no Week 5 loop is included.
- Tool names come from a fixed registry, never dynamic lookup.
- Tool input/output validation remains owned by the concrete tool.
- Approval-required tools fail closed when the gate is missing or unusable.
- Error messages exclude exception text and possible secrets.
- Demo adapters are labelled and cannot be mistaken for production tools.

## Verification I Performed

- Ran all 16 dispatcher tests successfully.
- Ran the four-scenario offline demo successfully.
- Parsed the five-page Draw.io XML successfully.
- Exported and visually inspected the L4 PNG.
- Checked each diff and committed changes incrementally.

No API keys, credentials, confidential data, or unrestricted repository content
were sent to a model. The repository uses team-created and synthetic fixtures.
I remain responsible for the submitted code and documentation.
