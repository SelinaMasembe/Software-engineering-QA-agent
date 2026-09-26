"""The draft_issue tool: prepare a human-reviewable issue draft, never submit one.

Submission is out of scope entirely -- there is no GitHub client, no network
call, and no code path here that could reach one. ``models.types.IssueDraft``
already models exactly what this tool produces ("kept here so whoever
implements run_tests/draft_issue in Week 4 has a shared starting shape"), so
it's reused as-is rather than redefined, including its ``evidence_refs:
tuple[str, ...]`` shape (plain source-path strings, not the structured
``EvidenceRef`` ``ProposalSet.evidence`` uses) and its ``DraftStatus.DRAFT``
default -- only a human, elsewhere, may ever move a draft to ``SUBMITTED``.

This is a REQUIRES_APPROVAL tool. orchestrator.router only calls
``run()`` once its approval gate returns APPROVED; a DENIED or PENDING
verdict returns a DispatchResult before ``run()`` is ever reached, so this
file has no approval logic of its own to write.

Persistence is an in-memory ``DraftStore`` injected at construction, the same
dependency-injection style ``SearchRepoTool`` uses for its ``RetrievalPipeline``
-- no persistence mechanism existed anywhere in the repo to build on, and a
human-review step to consume these drafts doesn't exist yet either, so
nothing here should assume drafts must outlive one running session.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Collection, Iterable, Mapping

from models.types import DraftStatus, IssueDraft
from orchestrator import ToolRisk


class DraftStore:
    """In-memory collection of issue drafts, keyed by draft_id."""

    def __init__(self) -> None:
        self._drafts: dict[str, IssueDraft] = {}

    def save(self, draft: IssueDraft) -> None:
        self._drafts[draft.draft_id] = draft

    def get(self, draft_id: str) -> IssueDraft | None:
        return self._drafts.get(draft_id)

    def all(self) -> tuple[IssueDraft, ...]:
        return tuple(self._drafts.values())


class DraftIssueTool:
    """Approval-gated tool satisfying orchestrator.router's Tool Protocol."""

    name = "draft_issue"
    risk = ToolRisk.REQUIRES_APPROVAL

    def __init__(
        self,
        store: DraftStore,
        *,
        allowed_roles: Iterable[str] = ("developer",),
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self.store = store
        self.allowed_roles: Collection[str] = tuple(allowed_roles)
        self._id_factory = id_factory

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Require title, body, and at least one evidence reference.

        An unevidenced draft is rejected here, before an approval gate is
        ever consulted -- it must never reach ``run()`` at all.
        """

        if not isinstance(arguments, Mapping):
            raise ValueError("draft_issue arguments must be an object.")

        allowed_keys = {"title", "body", "evidence_refs"}
        missing = allowed_keys - set(arguments)
        if missing:
            raise ValueError(f"draft_issue is missing required argument(s): {sorted(missing)}.")
        unknown = set(arguments) - allowed_keys
        if unknown:
            raise ValueError(f"draft_issue received unknown argument(s): {sorted(unknown)}.")

        title = arguments["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("'title' must be a non-empty string.")

        body = arguments["body"]
        if not isinstance(body, str) or not body.strip():
            raise ValueError("'body' must be a non-empty string.")

        evidence_refs = arguments["evidence_refs"]
        if not isinstance(evidence_refs, (list, tuple)) or not evidence_refs:
            raise ValueError(
                "'evidence_refs' must be a non-empty list; an unevidenced "
                "draft may not be constructed."
            )
        normalized_refs: list[str] = []
        for ref in evidence_refs:
            if not isinstance(ref, str) or not ref.strip():
                raise ValueError("Every entry in 'evidence_refs' must be a non-empty string.")
            normalized_refs.append(ref)

        return {"title": title, "body": body, "evidence_refs": tuple(normalized_refs)}

    def run(
        self,
        arguments: Mapping[str, Any],
        context: Any,
    ) -> Mapping[str, Any]:
        """Persist the draft. Only reached once the dispatcher's gate approves."""

        draft = IssueDraft(
            draft_id=self._id_factory(),
            title=arguments["title"],
            body=arguments["body"],
            evidence_refs=tuple(arguments["evidence_refs"]),
            status=DraftStatus.DRAFT,
        )
        self.store.save(draft)

        return {
            "draft_id": draft.draft_id,
            "title": draft.title,
            "body": draft.body,
            "evidence_refs": list(draft.evidence_refs),
            "status": draft.status.value,
        }

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        draft_id = output.get("draft_id")
        title = output.get("title")
        body = output.get("body")
        evidence_refs = output.get("evidence_refs")
        status = output.get("status")

        if not isinstance(draft_id, str) or not draft_id:
            raise ValueError("draft_issue output must include a non-empty 'draft_id'.")
        if not isinstance(title, str) or not title:
            raise ValueError("draft_issue output must include a non-empty 'title'.")
        if not isinstance(body, str) or not body:
            raise ValueError("draft_issue output must include a non-empty 'body'.")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise ValueError("draft_issue output must include a non-empty 'evidence_refs' list.")
        if not all(isinstance(ref, str) and ref for ref in evidence_refs):
            raise ValueError("Every 'evidence_refs' entry must be a non-empty string.")
        if status != DraftStatus.DRAFT.value:
            raise ValueError(
                "draft_issue must only ever produce a draft; submission is out of scope."
            )

        return {
            "draft_id": draft_id,
            "title": title,
            "body": body,
            "evidence_refs": list(evidence_refs),
            "status": status,
        }
