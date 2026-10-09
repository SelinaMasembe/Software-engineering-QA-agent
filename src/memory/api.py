"""Member 3's Week 6 memory API: the one door the agent's context uses.

``ProposalMemory`` sits between Member 1's record schema (``schema.py``) and
Member 2's storage (``store.py``). Every write is built as a
``ProposalMemoryRecord`` first, so the schema validates it before
``MemoryStore.put`` sees it, and every read is rebuilt through
``ProposalMemoryRecord.from_dict`` so a damaged document raises instead of
returning partial data. The stored document is exactly ``record.to_dict()``:
module, key, title, requirement ID, target, status, three timestamps, a test
node ID and who rejected it. No diagnosis, test output, source code or log
text can reach the store through this module.

Memory is advisory context. Nothing here approves anything, runs anything or
gates a tool; a rejection recorded here does not stop a proposal from being
made again, it only lets the context say it was declined.

Retention is not decided. ``expires_after`` has no default so the choice is
made, visibly, by whoever builds the object. ``None`` stores records with no
expiry. Each write re-stamps the expiry from the clock, so a record that is
still being updated lives on.

Records are stored one namespace per module (``namespace_for_module``), with
the proposal key as the record ID. ``MemoryStore.list`` returns at most 1000
rows, so a module is capped at ``MAX_RECORDS_PER_MODULE`` records and a new
proposal past that raises rather than quietly fall off a truncated list.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta
from typing import Callable

from models.types import ProposalMemoryStatus, TestProposal

from .schema import ProposalMemoryRecord, normalize_module
from .store import MemoryStore, StoredMemory

NAMESPACE_PREFIX = "proposal-memory:"
MAX_RECORDS_PER_MODULE = 1000

_STATUS_ORDER = {
    ProposalMemoryStatus.REJECTED_BY_HUMAN: 0,
    ProposalMemoryStatus.RUN: 1,
    ProposalMemoryStatus.PROPOSED: 2,
}


class MemoryRecordError(ValueError):
    """A stored memory document is corrupt or does not belong where it was found."""


class UnknownProposalError(MemoryRecordError):
    """No memory record exists for the proposal key in this module."""


def namespace_for_module(module: str) -> str:
    """The store namespace holding one module's records."""

    return NAMESPACE_PREFIX + normalize_module(module)


class ProposalMemory:
    """Read and write the per-module record of proposed, run and rejected tests."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        expires_after: timedelta | None,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(store, MemoryStore):
            raise TypeError("ProposalMemory requires a MemoryStore.")
        if expires_after is not None and (
            not isinstance(expires_after, timedelta) or expires_after <= timedelta(0)
        ):
            raise ValueError("expires_after must be a positive timedelta or None.")
        if not callable(clock):
            raise ValueError("ProposalMemory requires a clock.")
        self._store = store
        self._expires_after = expires_after
        self._clock = clock

    # -- writes ---------------------------------------------------------------

    def record_proposal(
        self, module: str, proposal: TestProposal
    ) -> ProposalMemoryRecord:
        """Remember that ``proposal`` was made for ``module``.

        Idempotent: if the proposal's key already exists, the stored record is
        returned untouched (status and timestamps unchanged), including a
        rejected one, so the caller can see it was already declined.
        """

        canonical = normalize_module(module)
        now = self._now()
        record = ProposalMemoryRecord.from_test_proposal(
            module=canonical, proposal=proposal, proposed_at=now
        )
        namespace = namespace_for_module(canonical)
        existing = self._load(namespace, record.proposal_key)
        if existing is not None:
            return existing[0]
        if len(self._store.list(namespace, limit=MAX_RECORDS_PER_MODULE)) >= (
            MAX_RECORDS_PER_MODULE
        ):
            raise MemoryRecordError(
                f"Module {canonical!r} already holds {MAX_RECORDS_PER_MODULE} records."
            )
        self._store.put(
            namespace,
            record.proposal_key,
            record.to_dict(),
            expires_at=self._expiry(now),
            at=now,
        )
        return record

    def record_run(
        self, module: str, proposal_key: str, *, test_node_id: str | None = None
    ) -> ProposalMemoryRecord:
        """PROPOSED to RUN. Raises ``ValueError`` from any other state."""

        return self._advance(
            module, proposal_key, lambda record, now: record.mark_run(
                at=now, test_node_id=test_node_id
            )
        )

    def record_rejection(
        self, module: str, proposal_key: str, *, by: str
    ) -> ProposalMemoryRecord:
        """PROPOSED or RUN to REJECTED_BY_HUMAN. Final: it cannot be undone.

        ``by`` must identify the human who rejected the proposal. This is
        never an agent tool: it must only be called from a path that carries
        a real human decision, never from ``src/agent`` or ``src/tools``, and
        a test enforces that those packages do not import this module.
        """

        if not isinstance(by, str) or not by.strip():
            raise ValueError("by must be a non-blank human identifier.")
        return self._advance(
            module,
            proposal_key,
            lambda record, now: record.mark_rejected(by=by, at=now),
        )

    # -- reads ----------------------------------------------------------------

    def find(self, module: str, proposal_key: str) -> ProposalMemoryRecord | None:
        loaded = self._load(namespace_for_module(module), proposal_key)
        return None if loaded is None else loaded[0]

    def list_for_module(self, module: str) -> tuple[ProposalMemoryRecord, ...]:
        """Every record for ``module``, in a stable order (oldest proposal first)."""

        namespace = namespace_for_module(module)
        stored = self._store.list(namespace, limit=MAX_RECORDS_PER_MODULE)
        records = [self._rebuild(namespace, item) for item in stored]
        records.sort(key=lambda record: (record.proposed_at, record.proposal_key))
        return tuple(records)

    def render_for_prompt(self, module: str, *, max_records: int, max_chars: int) -> str:
        """The ``Memory`` block for the propose_action context.

        Order is fixed: human rejections first, then runs, then open
        proposals, newest first within each, ties broken by key. Whole lines
        are dropped to fit ``max_records`` and ``max_chars``, never cut, and
        the opening tag states how many of how many are shown. Everything
        stored is escaped, so a title cannot close the block or add a tag.
        The block is data for the model to read, not an instruction.
        """

        for name, value in (("max_records", max_records), ("max_chars", max_chars)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        canonical = normalize_module(module)
        records = sorted(
            self.list_for_module(canonical),
            key=lambda record: (
                _STATUS_ORDER[record.status],
                -record.proposed_at.timestamp(),
                record.proposal_key,
            ),
        )
        total = len(records)
        lines = [_render_line(record) for record in records[:max_records]]

        def block(shown: list[str]) -> str:
            tag = (
                f'<memory module="{html.escape(canonical, quote=True)}" '
                f'shown="{len(shown)}" total="{total}">'
            )
            return "\n".join([tag, *shown, "</memory>"])

        while lines and len(block(lines)) > max_chars:
            lines.pop()
        result = block(lines)
        if len(result) > max_chars:
            raise ValueError("max_chars is too small for an empty memory block.")
        return result

    # -- internals ------------------------------------------------------------

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("The clock must return a timezone-aware datetime.")
        return now

    def _expiry(self, now: datetime) -> datetime | None:
        return None if self._expires_after is None else now + self._expires_after

    def _advance(self, module, proposal_key, move) -> ProposalMemoryRecord:
        namespace = namespace_for_module(module)
        loaded = self._load(namespace, proposal_key)
        if loaded is None:
            raise UnknownProposalError(
                f"No memory record {proposal_key!r} exists for module "
                f"{normalize_module(module)!r}."
            )
        current, revision = loaded
        now = self._now()
        updated = move(current, now)
        self._store.put(
            namespace,
            proposal_key,
            updated.to_dict(),
            expires_at=self._expiry(now),
            expected_revision=revision,
            at=now,
        )
        return updated

    def _load(
        self, namespace: str, proposal_key: str
    ) -> tuple[ProposalMemoryRecord, int] | None:
        stored = self._store.get(namespace, proposal_key)
        if stored is None:
            return None
        return self._rebuild(namespace, stored), stored.revision

    @staticmethod
    def _rebuild(namespace: str, stored: StoredMemory) -> ProposalMemoryRecord:
        where = f"Memory record {stored.record_id!r} in {namespace!r}"
        try:
            record = ProposalMemoryRecord.from_dict(dict(stored.document))
        except (ValueError, TypeError) as exc:
            raise MemoryRecordError(f"{where} is corrupt.") from exc
        if namespace != NAMESPACE_PREFIX + record.module or (
            stored.record_id != record.proposal_key
        ):
            raise MemoryRecordError(f"{where} does not match its stored identity.")
        return record


def _render_line(record: ProposalMemoryRecord) -> str:
    text = f"- {record.status.value}: {record.title}"
    if record.requirement_id:
        text += f" [requirement {record.requirement_id}]"
    elif record.target:
        text += f" [target {record.target}]"
    return html.escape(text, quote=False)


__all__ = [
    "MAX_RECORDS_PER_MODULE",
    "MemoryRecordError",
    "ProposalMemory",
    "UnknownProposalError",
    "namespace_for_module",
]
