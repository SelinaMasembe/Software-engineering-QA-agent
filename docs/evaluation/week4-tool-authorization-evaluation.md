# Week 4 Tool Authorization & Failure Test Evidence

Stand-in tool implementations (tests/test_tool_auth.py), dispatched through the real src/orchestration/tool_dispatcher.py. Member 3's real tools were not yet on origin/feat/tools when this evidence was generated; swap STAND_IN_TOOL_CATALOGUE for the real tools once they land.

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

- Missing/malformed arguments: 12 cases across all four tools (tests/test_tool_auth.py::MissingAndMalformedArgumentTests)
- Path-traversal attempts on read_file: 7 cases (tests/test_tool_auth.py::PathTraversalSecurityTests)
- Unauthorized/adversarial requests: unregistered tool, non-tool action disguised as a tool call, malformed prompt-injection-style payload, side-effecting tool with no approval gate configured (tests/test_tool_auth.py::UnauthorizedAndAdversarialRequestTests)
- Approval boundary: role-based approve/pending, explicit deny, and approval-service failure (fails closed, no secret leakage) (tests/test_tool_auth.py::ApprovalBoundaryTests)
- Unexpected tool responses: tool exception, oversized output, non-mapping return value (tests/test_tool_auth.py::UnexpectedToolResponseTests)
