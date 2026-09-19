"""Turn one retrieval result into the evidence text a propose_action turn sees.

Trusts ``RetrievalPipeline.retrieve``'s ranking completely: chunks are never
re-sorted, re-filtered, or truncated internally here. A chunk is either shown
whole or dropped whole, so every ``source_path`` a model cites stays
verbatim-checkable against docs/prompts/propose_action/v1.1.md's citation
constraint.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chunking import Chunk, RetrievalConfigurationError
from .retrieval import RetrievalResult

# Rough estimate for English text and source code; good enough for a budget
# check, not an exact tokenizer.
CHARS_PER_TOKEN_ESTIMATE = 4
EVIDENCE_TOKEN_BUDGET = 6_000
EVIDENCE_CHAR_BUDGET = EVIDENCE_TOKEN_BUDGET * CHARS_PER_TOKEN_ESTIMATE

NO_EVIDENCE_MESSAGE = "No relevant evidence was found for this query."


@dataclass(frozen=True)
class AssembledContext:
    """The evidence block for one turn, plus what it's safe to cite from it."""

    text: str
    chunks_used: int
    chunks_dropped: int
    not_in_corpus: bool
    allowed_source_paths: frozenset[str]


def build_context(
    retrieval_result: RetrievalResult,
    *,
    char_budget: int = EVIDENCE_CHAR_BUDGET,
) -> AssembledContext:
    """Assemble the evidence block for one propose_action turn."""

    if char_budget <= 0:
        raise RetrievalConfigurationError("char_budget must be greater than zero.")

    if retrieval_result.not_in_corpus or not retrieval_result.chunks:
        return AssembledContext(
            text=NO_EVIDENCE_MESSAGE,
            chunks_used=0,
            chunks_dropped=0,
            not_in_corpus=True,
            allowed_source_paths=frozenset(),
        )

    included_blocks: list[str] = []
    included_paths: set[str] = set()
    used_chars = 0
    dropped = 0

    for retrieved in retrieval_result.chunks:
        block = _render_chunk(retrieved.chunk)
        # Always keep at least one chunk, even if it alone exceeds the
        # budget; an empty context is worse than an over-budget one.
        if used_chars + len(block) > char_budget and included_blocks:
            dropped += 1
            continue
        included_blocks.append(block)
        included_paths.add(retrieved.chunk.source_path)
        used_chars += len(block)

    return AssembledContext(
        text="\n".join(included_blocks),
        chunks_used=len(included_blocks),
        chunks_dropped=dropped,
        not_in_corpus=False,
        allowed_source_paths=frozenset(included_paths),
    )


def _render_chunk(chunk: Chunk) -> str:
    """Wrap one chunk in its evidence tag. Chunk text is never altered."""

    req_attr = (
        f' requirement_id="{chunk.requirement_id}"' if chunk.requirement_id else ""
    )
    return (
        f'<evidence source_path="{chunk.source_path}" '
        f'doc_type="{chunk.doc_type.value}"{req_attr}>\n'
        f"{chunk.text}\n"
        f"</evidence>"
    )
