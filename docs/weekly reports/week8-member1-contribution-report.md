# Week 8 Contribution Report: Member 1 (Project/Requirements Lead)

**Date:** 22 October 2026  
**Project:** Software-Engineering QA Agent  
**Course:** BSE4104 — Emerging Trends in Software Engineering  
**Group:** J

## Summary

This week I completed the requirements and traceability review for the final
report. I reviewed the scenario-to-user-story mappings, checked the domain
types used by the proposal-validation flow, strengthened the automated
traceability checks, and prepared the Executive Summary and Problem Context
sections of the final engineering report.

The main issue found was not a runtime failure. The scenario
`boundary_single_action_multiple_candidates` was described in the
traceability document as indirect evidence for US-9, but the executable
mapping left it undocumented. I corrected the mapping and made the
distinction explicit: the case is evidence for the bounded single-action
design, but it does not by itself prove the iteration-cap halt.

## Work completed

| Work | File | Result |
|---|---|---|
| Reviewed the domain model and proposal-validation types | `src/models/types.py` | Confirmed `ProposalSet.model_validate_json` and `TestProposal.validate_sources` support the requirements and citation guardrail |
| Strengthened scenario-to-story traceability | `tests/test_scenario_coverage.py` | Added mapping validation for duplicate IDs, unknown cases, unknown stories, missing mappings, and documented exceptions |
| Recorded indirect US-9 evidence | `tests/test_scenario_coverage.py` | Mapped `boundary_single_action_multiple_candidates` to US-9 as indirect evidence |
| Updated traceability documentation | `docs/requirements/week2-test-case-traceability.md` | Removed stale “open” wording and documented the intentional US-1/US-2 dual mapping |
| Drafted final report Sections 1 and 2 | `docs/evaluation/final-report-sections-1-2.md` | Added Executive Summary and Problem Context |
| Produced Word deliverable | `docs/evaluation/Final_Report_Sections_1_and_2.docx` | Generated and validated a readable DOCX report |

## Traceability improvements

The coverage test now treats every evaluation case explicitly. A case must
either have a user-story mapping or appear in the documented exception set.
The test also verifies that mapped case IDs and user-story IDs are valid and
that the corresponding references are present in the traceability document.
This prevents the executable mapping and the written requirements evidence
from silently drifting apart.

The following scope remains intentional:

- US-1, US-2, US-7, US-8, and US-11 have direct active prompt-evaluation
  evidence.
- US-9 has indirect evidence from the one-action boundary case, while a
  dedicated iteration-cap scenario remains desirable.
- US-3, US-4, US-5, US-6, and US-10 require dedicated tool-backed or
  multi-turn scenarios and are not incorrectly marked as covered by the
  ten-case prompt fixture.
- `failure_malformed_source_code` remains a documented contract-level
  exception rather than an invented user story.

## Validation evidence

The focused `ScenarioCoverageTests` suite passed all five tests:

1. all active stories are covered;
2. the boundary case is recorded as indirect US-9 evidence;
3. deferred stories are not treated as failures;
4. the edge-stub case covers both US-1 and US-2; and
5. the executable mapping agrees with the fixture and traceability document.

The edited Python test file also passed syntax validation and produced no
editor diagnostics. The report DOCX was checked as a valid Office Open XML
package containing the required document parts.

## Remaining recommendations

The next requirements task should add dedicated scenarios for the deferred
stories once the approval gate, sandbox execution, failure-summary, draft
issue, stop-condition, and audit-trace workflows are exercised together.
Those scenarios should be added to the same traceability validation so that
future report revisions remain synchronized with the executable evaluation
suite.
