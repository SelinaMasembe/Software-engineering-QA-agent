# Week 7 — Member 4 Failure Catalogue and automated re-tests

Date: 16 October 2026.

Deliverables: `docs/evaluation/week7-failure-catalogue.md`,
`tests/test_failure_retest.py`, and
`evidence/evaluation/week7-failure-retest.json`.

**What I asked the AI for:** Understand the existing QA agent and Member 4's
work, create a branch from main for Week 7, and help complete the task to document
at least five real failures and automatically re-run them to confirm the fixes.

**What the AI produced:** Codex read the task allocation plan and capstone brief,
fetched main and created `week7-member4-failure-retest` from `origin/main` at
`3df49eb`. It inspected actual fixing commits and wrote five regression cases for
corpus path escape, forged memory entries, self-approval, unauthorized-request
mutation and telemetry deadlock. It wrote the catalogue and a runner that checks
current code and optionally loads the exact before/fixed modules from Git in
isolated subprocesses. It generated JSON evidence with observations and source
hashes. Production code was not changed; the original fixes are credited to
Ann Karagwa, Selina Masembe and Andrew in the catalogue.

**Verification performed by the AI:** The historical run reproduced all five
expected assertion failures and passed all five fixing-module checks and all
five current-code checks. Full-suite and sensitive-data verification results
are recorded in `evidence/evaluation/week7-verification.md`.

**Verification I performed myself:** Pending. The preceding results were run by
the AI in this workspace, not personally verified by Member 4. Before submission,
run the catalogue command and the full suite, inspect the JSON failure details,
and replace this paragraph with the actual personal verification performed.

**What I changed or would still change myself:** Review the selected failures,
the attribution of each historical fix, and the module-level reproduction limit.
The runner uses current dependencies with historical modules; it does not
rebuild old application environments. The 30-scenario evaluation and scoring
remain the other members' deliverables.

**Not AI-generated in this session:** The assignment, team allocation, existing
project implementation and original fixes. The decision to move to Week 7 and
request Member 4's deliverable came from the user.

**Data sent to the AI:** Repository source, tests, documentation, Git history,
the supplied assignment PDFs and task screenshot. No API keys, credentials or
production data were used.
