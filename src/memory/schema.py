"""Member 1's Week 6 memory schema: what one memory record looks like.

The single use case this project's memory serves is fixed by the charter
(Scope item v) and by the one sentence below, which every other document
that describes memory has to agree with:

    The agent remembers, for each repository module, which tests it has
    proposed, which of those were run, and which a human explicitly
    rejected, so that it never repeats a proposal a developer has already
    seen or declined; it does not remember or reuse past diagnoses.

That sentence is ``MEMORY_DESCRIPTION`` and it is the only description of
the memory in the code base. A record therefore holds exactly what the
sentence promises and nothing else: which module, which proposal, how far it
got (proposed, run, rejected by a human) and when, and who rejected it. It
has no field for a diagnosis, a failure summary, tool output, evidence text
or free-form notes, so none can be stored by accident. A test fails if
someone adds a field, as a prompt to check the change against the sentence.

Identity. A proposal has a title and a target but no test ID until someone
writes the test, and a rejected proposal never gets one, so a test ID cannot
be what memory is keyed on. ``make_proposal_key`` builds the key from the
module, an anchor (the requirement ID, else the target, else nothing) and a
normalised title. Normalising means case, punctuation and spacing are
ignored, so trivial rewording matches. The key is an exact match on that
normalised form, so a genuine paraphrase ("account locks after 5 failed
logins" for "lock account after five failures") is NOT caught here. That
gap is deliberate and recorded: the prompt shows the model its earlier
proposals as the soft layer, and this key is the deterministic backstop.

Each record is one proposal moving forward: PROPOSED, then RUN, and a human
may reject it from either state. REJECTED_BY_HUMAN is final. Records are
frozen; ``mark_run`` and ``mark_rejected`` return a new record and raise on
an invalid move, so the history cannot be rewritten by accident.

This module has no third-party dependency and does no I/O. Storing records
(a JSON file, like the approval store) is a separate piece that builds on
``to_dict`` and ``from_dict``. ``models.types.MemoryEntry`` (Week 2) is
left as it was; nothing used it, and this record replaces it.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from models.types import ProposalMemoryStatus, TestProposal

MEMORY_DESCRIPTION = (
    "The agent remembers, for each repository module, which tests it has "
    "proposed, which of those were run, and which a human explicitly "
    "rejected, so that it never repeats a proposal a developer has already "
    "seen or declined; it does not remember or reuse past diagnoses."
)

MAX_TITLE_CHARS = 300
MAX_TEXT_CHARS = 300

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


# ---------------------------------------------------------------------------
# Normalisation and the proposal key.
# ---------------------------------------------------------------------------


def normalize_module(module: str) -> str:
    """Return the canonical form of a module path, or raise ``ValueError``.

    A module is a repo-relative path written with forward slashes and no
    leading ``./``, for example ``src/billing/discounts.py``. Backslashes,
    repeated slashes, a leading ``./`` and a trailing slash are tidied so two
    spellings of one path cannot create two memories. Absolute paths and
    ``..`` segments are rejected: memory is about modules inside the repo.
    """

    if not isinstance(module, str):
        raise ValueError("module must be a string.")
    text = module.strip().replace("\\", "/")
    if not text:
        raise ValueError("module must not be empty.")
    if text.startswith("/") or _WINDOWS_DRIVE.match(text):
        raise ValueError("module must be a repo-relative path, not an absolute one.")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts:
        raise ValueError("module must name something inside the repository.")
    if ".." in parts:
        raise ValueError("module must not contain '..'.")
    return "/".join(parts)


def normalize_text(text: str) -> str:
    """Lowercase, fold accents, and flatten punctuation and spacing."""

    folded = unicodedata.normalize("NFKC", text).lower()
    return _NON_ALNUM.sub(" ", folded).strip()


def make_proposal_key(
    module: str,
    *,
    title: str,
    requirement_id: str | None = None,
    target: str | None = None,
) -> str:
    """Deterministic identity of a proposal within a module.

    The anchor is the requirement ID when there is one, otherwise the
    target, otherwise empty. Two proposals with the same module, anchor and
    normalised title have the same key. See the module docstring for what
    this does and does not catch.
    """

    if not isinstance(title, str) or not normalize_text(title):
        raise ValueError("title must contain at least one letter or digit.")
    anchor = requirement_id or target or ""
    basis = "|".join(
        (normalize_module(module), normalize_text(anchor), normalize_text(title))
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# The record.
# ---------------------------------------------------------------------------

_FIELDS = (
    "module",
    "proposal_key",
    "title",
    "requirement_id",
    "target",
    "status",
    "proposed_at",
    "run_at",
    "test_node_id",
    "rejected_at",
    "rejected_by",
)


def _require_aware(name: str, value: datetime | None, *, required: bool) -> None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required.")
        return
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")


def _optional_text(name: str, value: str | None) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string when given.")
    if value != value.strip():
        raise ValueError(f"{name} must not have leading or trailing spaces.")
    if len(value) > MAX_TEXT_CHARS:
        raise ValueError(f"{name} must be at most {MAX_TEXT_CHARS} characters.")


@dataclass(frozen=True)
class ProposalMemoryRecord:
    """One proposal the agent has made for one module, and how far it got."""

    module: str
    proposal_key: str
    title: str
    status: ProposalMemoryStatus
    proposed_at: datetime
    requirement_id: str | None = None
    target: str | None = None
    run_at: datetime | None = None
    test_node_id: str | None = None
    rejected_at: datetime | None = None
    rejected_by: str | None = None

    def __post_init__(self) -> None:
        if self.module != normalize_module(self.module):
            raise ValueError(
                "module must already be in canonical form; use normalize_module."
            )
        if not isinstance(self.title, str) or not normalize_text(self.title):
            raise ValueError("title must contain at least one letter or digit.")
        if len(self.title) > MAX_TITLE_CHARS:
            raise ValueError(f"title must be at most {MAX_TITLE_CHARS} characters.")
        _optional_text("requirement_id", self.requirement_id)
        _optional_text("target", self.target)
        _optional_text("test_node_id", self.test_node_id)
        _optional_text("rejected_by", self.rejected_by)
        if not isinstance(self.status, ProposalMemoryStatus):
            raise ValueError("status must be a ProposalMemoryStatus.")

        expected_key = make_proposal_key(
            self.module,
            title=self.title,
            requirement_id=self.requirement_id,
            target=self.target,
        )
        if self.proposal_key != expected_key:
            raise ValueError("proposal_key does not match module, anchor and title.")

        _require_aware("proposed_at", self.proposed_at, required=True)
        _require_aware("run_at", self.run_at, required=False)
        _require_aware("rejected_at", self.rejected_at, required=False)

        if self.test_node_id is not None and self.run_at is None:
            raise ValueError("test_node_id can only be set once the test has been run.")
        if self.run_at is not None and self.run_at < self.proposed_at:
            raise ValueError("run_at must not be before proposed_at.")
        if self.rejected_at is not None:
            if self.rejected_at < self.proposed_at:
                raise ValueError("rejected_at must not be before proposed_at.")
            if self.run_at is not None and self.rejected_at < self.run_at:
                raise ValueError("rejected_at must not be before run_at.")

        status = self.status
        rejected = self.rejected_at is not None or self.rejected_by is not None
        if status is ProposalMemoryStatus.PROPOSED:
            if self.run_at is not None or rejected:
                raise ValueError("a PROPOSED record has not been run or rejected.")
        elif status is ProposalMemoryStatus.RUN:
            if self.run_at is None:
                raise ValueError("a RUN record needs run_at.")
            if rejected:
                raise ValueError("a RUN record has not been rejected.")
        else:
            if self.rejected_at is None or self.rejected_by is None:
                raise ValueError(
                    "a REJECTED_BY_HUMAN record needs rejected_at and rejected_by."
                )

    # -- construction -------------------------------------------------------

    @classmethod
    def propose(
        cls,
        *,
        module: str,
        title: str,
        proposed_at: datetime,
        requirement_id: str | None = None,
        target: str | None = None,
    ) -> "ProposalMemoryRecord":
        """Record a new proposal. The module is normalised for the caller."""

        canonical = normalize_module(module)
        return cls(
            module=canonical,
            proposal_key=make_proposal_key(
                canonical, title=title, requirement_id=requirement_id, target=target
            ),
            title=title,
            status=ProposalMemoryStatus.PROPOSED,
            proposed_at=proposed_at,
            requirement_id=requirement_id,
            target=target,
        )

    @classmethod
    def from_test_proposal(
        cls, *, module: str, proposal: TestProposal, proposed_at: datetime
    ) -> "ProposalMemoryRecord":
        """Build the record for a ``TestProposal`` the agent just made."""

        if not isinstance(proposal, TestProposal):
            raise TypeError("from_test_proposal requires a TestProposal.")
        return cls.propose(
            module=module,
            title=proposal.title,
            proposed_at=proposed_at,
            requirement_id=proposal.requirement_id,
            target=proposal.target,
        )

    # -- moves forward ------------------------------------------------------

    def mark_run(
        self, *, at: datetime, test_node_id: str | None = None
    ) -> "ProposalMemoryRecord":
        """PROPOSED to RUN. Anything else raises ``ValueError``."""

        if self.status is not ProposalMemoryStatus.PROPOSED:
            raise ValueError(f"only a PROPOSED record can be run, not {self.status.value}.")
        return replace(
            self, status=ProposalMemoryStatus.RUN, run_at=at, test_node_id=test_node_id
        )

    def mark_rejected(self, *, by: str, at: datetime) -> "ProposalMemoryRecord":
        """PROPOSED or RUN to REJECTED_BY_HUMAN, which is final."""

        if self.status is ProposalMemoryStatus.REJECTED_BY_HUMAN:
            raise ValueError("a rejected record is final and cannot be rejected again.")
        return replace(
            self,
            status=ProposalMemoryStatus.REJECTED_BY_HUMAN,
            rejected_at=at,
            rejected_by=by,
        )

    # -- JSON-safe form -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        def stamp(value: datetime | None) -> str | None:
            return None if value is None else value.isoformat()

        return {
            "module": self.module,
            "proposal_key": self.proposal_key,
            "title": self.title,
            "requirement_id": self.requirement_id,
            "target": self.target,
            "status": self.status.value,
            "proposed_at": stamp(self.proposed_at),
            "run_at": stamp(self.run_at),
            "test_node_id": self.test_node_id,
            "rejected_at": stamp(self.rejected_at),
            "rejected_by": self.rejected_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProposalMemoryRecord":
        """Rebuild and re-validate a record. Unknown or missing keys raise."""

        if not isinstance(data, dict):
            raise ValueError("a memory record must be a JSON object.")
        unknown = set(data) - set(_FIELDS)
        if unknown:
            raise ValueError(f"unknown memory record fields: {sorted(unknown)}.")
        missing = set(_FIELDS) - set(data)
        if missing:
            raise ValueError(f"missing memory record fields: {sorted(missing)}.")

        def parse(name: str) -> datetime | None:
            raw = data[name]
            if raw is None:
                return None
            if not isinstance(raw, str):
                raise ValueError(f"{name} must be an ISO-8601 string or null.")
            try:
                return datetime.fromisoformat(raw)
            except ValueError as exc:
                raise ValueError(f"{name} is not a valid ISO-8601 time.") from exc

        try:
            status = ProposalMemoryStatus(data["status"])
        except ValueError as exc:
            raise ValueError("status is not a known memory status.") from exc

        return cls(
            module=data["module"],
            proposal_key=data["proposal_key"],
            title=data["title"],
            status=status,
            proposed_at=parse("proposed_at"),  # type: ignore[arg-type]
            requirement_id=data["requirement_id"],
            target=data["target"],
            run_at=parse("run_at"),
            test_node_id=data["test_node_id"],
            rejected_at=parse("rejected_at"),
            rejected_by=data["rejected_by"],
        )
