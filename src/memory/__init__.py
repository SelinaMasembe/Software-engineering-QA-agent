"""Week 6: the agent's single, bounded memory use case (see schema.py)."""

from .schema import (
    MAX_TEXT_CHARS,
    MAX_TITLE_CHARS,
    MEMORY_DESCRIPTION,
    ProposalMemoryRecord,
    make_proposal_key,
    normalize_module,
    normalize_text,
)

__all__ = [
    "MAX_TEXT_CHARS",
    "MAX_TITLE_CHARS",
    "MEMORY_DESCRIPTION",
    "ProposalMemoryRecord",
    "make_proposal_key",
    "normalize_module",
    "normalize_text",
]
