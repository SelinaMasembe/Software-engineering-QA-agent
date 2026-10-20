Date: 2026-10-20
Deliverable: src/agent/loop.py fix + tests/test_loop_injection_trace.py — Week 8 guardrail bug

What I asked the AI for: Help reviewing the guardrail code for real bugs
during the Week 8 hardening pass, since the task was to finish the
evaluation and evidence pack and fix any guardrail bugs found.

What the AI produced: Found that AssembledContext.flagged (injection and
credential flags detected per chunk) was computed every turn but never read
by AgentLoop — the function written specifically to put a flag into the
trace was called only by its own tests, so a real session never actually
recorded that a chunk had been flagged. Implemented the fix and five tests
proving it, then folded it into the existing failure-retest harness as a
sixth, history-verified case (the commit before the fix reproduces the gap;
the fix resolves it).

Verification I performed myself: Ran the full test suite
(676 tests) and the combined 61-scenario evaluation runner before and after
the fix, and read the before/after trace output directly to confirm the
fix changes what I expected it to and nothing else.

What I changed or would still change myself: The fix only surfaces flags in
the trace for review, per how the guardrail was originally specified
(flag, don't remove). Whether flagged content should ever trigger something
stronger than a trace entry is a product decision I didn't make here.

Not AI-generated: The decision that this gap counted as a genuine
guardrail bug worth fixing, rather than a documentation note, was mine.

Data sent to the AI: Only this repository's own source code and test
fixtures. No credentials, API keys, or external/confidential data.
