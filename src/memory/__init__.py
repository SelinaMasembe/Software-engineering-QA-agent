"""Week 6 memory and persistent-state boundary for the QA agent.

The agent's single, bounded memory use case is defined in ``schema.py``;
storage and explicit session state are in ``store.py``.
"""

from .schema import (
    MAX_TEXT_CHARS,
    MAX_TITLE_CHARS,
    MEMORY_DESCRIPTION,
    ProposalMemoryRecord,
    make_proposal_key,
    normalize_module,
    normalize_text,
)
from .store import (
    MemoryStore,
    SessionPhase,
    SessionState,
    StateTransitionError,
    StoreClosedError,
    StoreConflictError,
    StoredMemory,
)

__all__ = [
    "MAX_TEXT_CHARS",
    "MAX_TITLE_CHARS",
    "MEMORY_DESCRIPTION",
    "ProposalMemoryRecord",
    "make_proposal_key",
    "normalize_module",
    "normalize_text",
    "MemoryStore",
    "SessionPhase",
    "SessionState",
    "StateTransitionError",
    "StoreClosedError",
    "StoreConflictError",
    "StoredMemory",
]
