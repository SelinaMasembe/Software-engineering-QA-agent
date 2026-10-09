Date: 2026-10-09
Deliverable: tests/test_memory_guard.py — Week 6 memory/approval security review

What I asked the AI for: Help reviewing whether the new memory system
(src/memory/) could let the agent skip a required approval
(src/orchestrator/approval_gate.py), and writing a test that fails the
build if it ever does.

What the AI produced: Four independent checks, each backed by a test rather
than asserted from reading the code once: that the approval gate's real
signature has no memory-shaped parameter, that memory's status enum has no
"approved" value, a dynamic (subprocess-based) check that src/agent/ and
src/tools/ never import memory.api, and a behavioural test dispatching the
same approval-required request through the real dispatcher and gate with
memory in every possible state, confirming the outcome never changes.

Verification I performed myself: Ran the suite
(`PYTHONPATH=src python3 -m unittest tests.test_memory_guard -v`) and
confirmed all 10 tests pass. Ran the full repository suite (398 tests) to
confirm nothing else broke.

What I changed or would still change myself: The dynamic import check
duplicates, in spirit, a static AST-based check a teammate had already
written for the same boundary. I kept both rather than removing mine, since
they catch different things (a direct import vs. an indirect one) — but I
noted the overlap explicitly in the file so it reads as a deliberate choice,
not an oversight.

Not AI-generated: The decision of what counts as "memory letting the agent
skip approval" — i.e. which four findings actually matter here — came from
reading the real approval gate and memory code myself, not from the AI.

Data sent to the AI: Only this repository's own source code and test
fixtures. No credentials, API keys, or external/confidential data.
