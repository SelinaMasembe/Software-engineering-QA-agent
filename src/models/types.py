"""Domain model types for the Software-Engineering QA Agent.

Week 2 deliverable (Member 1 - Project/Requirements Lead): simple data types
for the nouns the twelve user stories in
docs/requirements/Project_charter and user stories.docx talk about - a
Requirement, a TestProposal, and so on.

Two of these types are wired directly into code the rest of the team already
wrote, not just illustrative:

- ``ProposalSet.model_validate_json`` is the exact hook
  src/rag/pipeline.py's ``generate_test_proposals`` docstring names ("The
  parser may be replaced with Member 1's ProposalSet.model_validate_json
  method"). Pass it as ``response_parser`` to get a typed, schema-checked
  result instead of the default raw dict.
- ``TestProposal.validate_sources`` enforces US-8's negative case in code
  (reject a proposal with no traceable reference, or one that cites a
  source_path never actually supplied) rather than only asking the model
  nicely in the prompt. This is exactly what
  tests/fixtures/prompt_eval_cases.json's
  ``adversarial_fabricated_citation_temptation`` case checks for.

Everything else here (CoverageGap, ApprovalDecision, SandboxExecutionResult,
FailureSummary, IssueDraft, TraceEntry, ...) is forward-looking vocabulary
for stories the Week 2 propose_action prompt doesn't exercise yet (US-3
through US-6, US-9, US-10 - see
docs/requirements/week2-test-case-traceability.md for why), kept here so
whoever implements run_tests/draft_issue in Week 4 has a shared starting
shape rather than inventing one on the spot.

No third-party dependency is introduced. The project has none so far (see
client.py's hand-rolled urllib call in place of an HTTP library), so
``model_validate_json`` parses and validates with the standard library only
- named to match the method a Pydantic BaseModel would expose for the same
job, so swapping this dataclass for an actual pydantic model later would not
change any call site, without forcing that dependency on the team now.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .client import ModelResponseError

# ---------------------------------------------------------------------------
# The propose_action contract (docs/prompts/propose_action/v1.1.md) - this
# is the ONE prompt/capability Week 2 actually builds and evaluates.
# ---------------------------------------------------------------------------


class Action(str, Enum):
    """The six actions propose_action v1.1 is allowed to return."""

    SEARCH_REPO = "search_repo"
    READ_FILE = "read_file"
    RUN_TESTS = "run_tests"
    DRAFT_ISSUE = "draft_issue"
    PROPOSE_TEST = "propose_test"
    NO_ACTION = "no_action"


class Confidence(str, Enum):
    """US-7: low, rather than a guess presented as fact."""

    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class EvidenceRef:
    """One cited source. Must be copied verbatim from the context a turn was
    actually given (propose_action v1.1, CONSTRAINTS) - never invented.
    """

    source_path: str
    note: str = ""


@dataclass(frozen=True)
class Requirement:
    """A requirement/spec clause the agent was given for one module (US-1)."""

    text: str
    source_path: str
    requirement_id: str | None = None


_REQUIRED_PROPOSAL_FIELDS = ("action", "arguments", "rationale", "evidence", "confidence")


@dataclass(frozen=True)
class ProposalSet:
    """One validated propose_action response - the five fields defined in
    docs/prompts/propose_action/v1.1.md's OUTPUT FORMAT, typed instead of a
    raw dict.
    """

    action: Action
    arguments: dict[str, Any]
    rationale: str
    evidence: tuple[EvidenceRef, ...]
    confidence: Confidence

    @classmethod
    def model_validate_json(cls, raw_text: str) -> "ProposalSet":
        """Parse and schema-validate one raw model response.

        Mirrors tests/test_prompt_harness.py's parse_propose_action_output,
        as a reusable type instead of a test-only helper, so application
        code and the evaluation harness both validate against one
        definition of the contract.
        """
        text = raw_text.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ModelResponseError("The model did not return valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ModelResponseError("The model response must be a JSON object.")

        missing = [f for f in _REQUIRED_PROPOSAL_FIELDS if f not in parsed]
        if missing:
            raise ModelResponseError(
                f"Model output is missing required field(s): {', '.join(missing)}."
            )

        try:
            action = Action(parsed["action"])
        except ValueError as exc:
            raise ModelResponseError(
                f"Model returned an unknown action: {parsed['action']!r}."
            ) from exc

        try:
            confidence = Confidence(parsed["confidence"])
        except ValueError as exc:
            raise ModelResponseError(
                f"Model returned an unknown confidence value: {parsed['confidence']!r}."
            ) from exc

        if not isinstance(parsed["evidence"], list):
            raise ModelResponseError("Model 'evidence' field must be a list.")
        evidence: list[EvidenceRef] = []
        for entry in parsed["evidence"]:
            if not isinstance(entry, dict) or "source_path" not in entry:
                raise ModelResponseError(
                    "Every evidence entry must be an object with a 'source_path'."
                )
            evidence.append(
                EvidenceRef(source_path=entry["source_path"], note=entry.get("note", ""))
            )

        if not isinstance(parsed["rationale"], str):
            raise ModelResponseError("Model 'rationale' field must be a string.")
        if not isinstance(parsed["arguments"], dict):
            raise ModelResponseError("Model 'arguments' field must be an object.")

        return cls(
            action=action,
            arguments=parsed["arguments"],
            rationale=parsed["rationale"],
            evidence=tuple(evidence),
            confidence=confidence,
        )


class UntraceableProposalError(ModelResponseError):
    """US-8: raised instead of silently passing a proposal through with a
    missing or fabricated citation."""


@dataclass(frozen=True)
class TestProposal:
    """A proposed test, once ``action == PROPOSE_TEST`` (US-1, US-7, US-8).

    Kept separate from ProposalSet so code that only cares about "here is a
    proposed test" doesn't need to know about the other five actions in the
    wire format.
    """

    title: str
    target: str | None
    rationale: str
    evidence: tuple[EvidenceRef, ...]
    confidence: Confidence
    requirement_id: str | None = None

    @classmethod
    def from_proposal_set(
        cls, proposal: ProposalSet, *, requirement_id: str | None = None
    ) -> "TestProposal":
        if proposal.action is not Action.PROPOSE_TEST:
            raise ValueError(
                f"from_proposal_set expects action={Action.PROPOSE_TEST!r}, "
                f"got {proposal.action!r}."
            )
        return cls(
            title=str(proposal.arguments.get("title", "")),
            target=proposal.arguments.get("target"),
            rationale=proposal.rationale,
            evidence=proposal.evidence,
            confidence=proposal.confidence,
            requirement_id=requirement_id,
        )

    def validate_sources(self, allowed_source_paths: set[str]) -> None:
        """US-8's negative case, enforced rather than only requested in the
        prompt: reject a proposal with no traceable reference, or one that
        cites a source_path never actually supplied this turn.

        This is exactly what
        tests/fixtures/prompt_eval_cases.json's
        adversarial_fabricated_citation_temptation case is designed to
        catch (citing pricing/discount_table.md, which was never provided).
        Call this on every propose_test result before it reaches a human
        reviewer.
        """
        if not self.evidence:
            raise UntraceableProposalError(
                f"Proposal {self.title!r} has no evidence and must be "
                "rejected, not passed through with a missing citation."
            )
        for ref in self.evidence:
            if ref.source_path not in allowed_source_paths:
                raise UntraceableProposalError(
                    f"Proposal {self.title!r} cites {ref.source_path!r}, "
                    "which was not provided in this turn's context "
                    "(fabricated citation)."
                )


@dataclass(frozen=True)
class CoverageGap:
    """A public function with no corresponding requirement or test (US-2).

    The propose_action schema has no separate "flag_gap" action - a stub or
    untested function is surfaced by proposing a test that targets it (see
    prompt_eval_cases.json's edge_stub_implementation case). This type is
    for whoever assembles the human-facing report, so that "propose_test on
    an untested function" gets called out explicitly as a coverage gap
    rather than looking like an ordinary proposal.
    """

    module: str
    function_name: str
    reason: str


# ---------------------------------------------------------------------------
# Vocabulary for stories the Week 2 prompt doesn't exercise yet (US-3 to
# US-6, US-9, US-10 - see docs/requirements/week2-test-case-traceability.md).
# Kept here so Week 4/5 implementers share a starting shape.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalDecision:
    """The human-supplied "approved" list for a session (US-3)."""

    session_id: str
    approved_test_ids: tuple[str, ...]
    decided_by: str
    decided_at: datetime


class RejectionReason(str, Enum):
    """Why run_tests refused a request - always rejected+logged, never
    silent (US-3, US-4)."""

    NOT_APPROVED = "not_approved_for_session"
    OUTSIDE_SANDBOX = "outside_sandbox"
    SECRET_ACCESS_ATTEMPT = "secret_access_attempt"
    UNKNOWN_TEST_NODE_ID = "unknown_test_node_id"


@dataclass(frozen=True)
class RejectedExecution:
    """A logged refusal to run something (US-3, US-4)."""

    session_id: str
    test_id: str
    reason: RejectionReason
    logged_at: datetime


class TestOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


@dataclass(frozen=True)
class TestResult:
    """One test's outcome from a sandboxed run_tests call."""

    test_id: str
    outcome: TestOutcome
    duration_ms: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SandboxExecutionResult:
    """US-4: exclusively-sandbox output for a session, plus anything that
    was requested but refused, right alongside what actually ran."""

    session_id: str
    results: tuple[TestResult, ...]
    rejected: tuple[RejectedExecution, ...] = ()


@dataclass(frozen=True)
class FailureSummary:
    """US-5: a plain-language explanation. ``log_excerpt`` is required, not
    optional - the acceptance criterion added in the Week 1 review is that
    the likely cause must cite the specific log line it's based on."""

    test_id: str
    likely_cause: str
    log_excerpt: str
    suggested_next_step: str


class DraftStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"  # only ever set by the human-approval step


@dataclass(frozen=True)
class IssueDraft:
    """US-6: the agent may prepare this; only a human may move it to
    SUBMITTED."""

    draft_id: str
    title: str
    body: str
    evidence_refs: tuple[str, ...]
    status: DraftStatus = DraftStatus.DRAFT


class StopReason(str, Enum):
    """US-9: four stop conditions, all deterministic."""

    ITERATION_CAP = "iteration_cap"
    WALL_CLOCK_BUDGET = "wall_clock_budget"
    REPEATED_CALL_DETECTED = "repeated_call_detected"
    NO_NEW_INFORMATION = "no_new_information"


@dataclass(frozen=True)
class LoopHaltEvent:
    """US-9: the halt itself must appear in the trace/log."""

    session_id: str
    reason: StopReason
    iteration_count: int
    halted_at: datetime


class Actor(str, Enum):
    AI = "ai"
    DETERMINISTIC = "deterministic"
    HUMAN = "human"


@dataclass(frozen=True)
class ToolInvocation:
    """One call to search_repo / read_file / run_tests / draft_issue."""

    tool_name: str
    input: dict[str, Any]
    output: dict[str, Any]
    called_at: datetime


@dataclass(frozen=True)
class TraceEntry:
    """US-10: every tool call and every agent decision produces one of
    these, so a session can be reconstructed after the fact."""

    session_id: str
    actor: Actor
    action: str
    detail: str
    timestamp: datetime
    tool_invocation: ToolInvocation | None = None


class InjectionSource(str, Enum):
    """US-11: the refusal applies the same way regardless of where the
    instruction came from."""

    TYPED_IN_SESSION = "typed_in_session"
    INGESTED_REQUIREMENT = "ingested_requirement"
    INGESTED_SOURCE_COMMENT = "ingested_source_comment"
    INGESTED_TEST_LOG = "ingested_test_log"


@dataclass(frozen=True)
class BoundaryViolationAttempt:
    """US-11: a flagged, declined attempt to bypass the safety boundary,
    whether typed directly or smuggled in through retrieved content."""

    session_id: str
    source: InjectionSource
    requested_action: str
    declined: bool
    flagged_at: datetime


class ProposalMemoryStatus(str, Enum):
    PROPOSED = "proposed"
    RUN = "run"
    REJECTED_BY_HUMAN = "rejected_by_human"


@dataclass(frozen=True)
class MemoryEntry:
    """What the agent remembers per module, so it never repeats a proposal
    a developer has already seen or declined (Charter, Section 6, item v)."""

    module: str
    test_id: str
    status: ProposalMemoryStatus
    recorded_at: datetime
