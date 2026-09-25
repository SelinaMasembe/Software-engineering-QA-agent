# Week 4 Tool Authorization & Failure Test Evidence

The four REAL tools from src/tools/ (Member 3, feat/tools), dispatched through the real src/orchestrator/tool_dispatcher.py (Member 2). The per-tool `allowed_roles` policy exercised here is Member 4's own proposed default access matrix -- no team-wide role policy is wired into the application yet; the enforcement mechanism is real, this specific role set is illustrative.

## Authorization matrix

| Tool | Role | Declared allowed | Dispatch status | Code |
| --- | --- | --- | --- | --- |
| search_repo | developer | True | executed | - |
| search_repo | quality_lead | True | executed | - |
| search_repo | maintainer | True | executed | - |
| search_repo | guest | False | rejected | unauthorized |
| read_file | developer | True | executed | - |
| read_file | quality_lead | True | executed | - |
| read_file | maintainer | True | executed | - |
| read_file | guest | False | rejected | unauthorized |
| run_tests | developer | True | executed | - |
| run_tests | quality_lead | True | executed | - |
| run_tests | maintainer | True | executed | - |
| run_tests | guest | False | rejected | unauthorized |
| draft_issue | developer | False | rejected | unauthorized |
| draft_issue | quality_lead | True | executed | - |
| draft_issue | maintainer | True | executed | - |
| draft_issue | guest | False | rejected | unauthorized |

Matrix rows: 16. Mismatches between declared access and observed dispatch outcome: 0.

## Failure-case coverage

- Missing/malformed arguments: 14 cases across all four real tools (tests/test_tool_auth.py::MissingAndMalformedArgumentTests)
- read_file allow-list boundary: registered-but-missing file vs. unregistered path (including traversal strings and an absolute path), proving the tool never reveals which unregistered paths exist on disk (tests/test_tool_auth.py::ReadFileAllowListTests)
- Unauthorized/adversarial requests: unregistered tool, non-tool action disguised as a tool call, malformed prompt-injection-style payload, side-effecting tool with no approval gate configured (tests/test_tool_auth.py::UnauthorizedAndAdversarialRequestTests)
- Approval boundary: role-based approve/pending, explicit deny, and approval-service failure (fails closed, no secret leakage) (tests/test_tool_auth.py::ApprovalBoundaryTests)
- Real tool failure modes: a genuinely failing sandboxed test (real subprocess), a hanging test killed by the real wall-clock timeout, and draft_issue's status invariant (tests/test_tool_auth.py::RealToolFailureAndEdgeCaseTests)
