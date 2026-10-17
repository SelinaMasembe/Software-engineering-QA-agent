"""Turn one retrieval result into the evidence text a propose_action turn sees.

Trusts ``RetrievalPipeline.retrieve``'s ranking completely: chunks are never
re-sorted, re-filtered, or truncated internally here. A chunk is either shown
whole or dropped whole, so every ``source_path`` a model cites stays
verbatim-checkable against docs/prompts/propose_action/v1.1.md's citation
constraint.

Each chunk is wrapped in one ``<evidence ...>`` block. The wrapper must be
the only thing that opens or closes a block, so two things are made safe
(risk R1): an evidence or memory tag inside chunk text has its leading
``<`` neutralised, and the attribute values (``source_path``, ``doc_type``,
``requirement_id``) cannot contain a quote, an angle bracket or a line break.

Credential-shaped strings in chunk text are replaced with
``[REDACTED:credential]`` before the model sees them (risk R4,
``credential_scan``). Everything else in a chunk is shown exactly as it is.
``allowed_source_paths`` always holds the original paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .chunking import Chunk, DocumentType, RetrievalConfigurationError
from .credential_scan import redact_credentials
from .injection_flagging import ChunkFlags, flag_text
from .retrieval import RetrievalResult

# Rough estimate for English text and source code; good enough for a budget
# check, not an exact tokenizer.
CHARS_PER_TOKEN_ESTIMATE = 4
EVIDENCE_TOKEN_BUDGET = 6_000
EVIDENCE_CHAR_BUDGET = EVIDENCE_TOKEN_BUDGET * CHARS_PER_TOKEN_ESTIMATE

NO_EVIDENCE_MESSAGE = "No relevant evidence was found for this query."

# An opening or closing ``evidence`` or ``memory`` tag in chunk text, any case,
# with optional whitespace around the slash and the name. Both are delimiters
# the model is shown: ``evidence`` wraps each chunk here, and ``memory`` wraps
# the proposal history from ``memory.api.ProposalMemory.render_for_prompt``.
# Only the "<" is matched, so every other "<" and ">" is left alone.
_EVIDENCE_TAG_START = re.compile(r"<(?=\s*/?\s*(?:evidence|memory)\b)", re.IGNORECASE)

# Characters that end a line, and so could break a tag or an attribute.
_LINE_BREAKS = "\r\n\v\f\x85\u2028\u2029"


@dataclass(frozen=True)
class AssembledContext:
    """The evidence block for one turn, plus what it's safe to cite from it."""

    text: str
    chunks_used: int
    chunks_dropped: int
    not_in_corpus: bool
    allowed_source_paths: frozenset[str]
    # Chunks shown to the model that matched an injection rule (R1, shown
    # unchanged, for review) or a credential rule (R4, the value is replaced
    # with [REDACTED:credential]). Spans refer to the original chunk text.
    flagged: tuple[ChunkFlags, ...] = ()


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
    flagged: list[ChunkFlags] = []
    included_paths: set[str] = set()
    used_chars = 0
    dropped = 0

    for retrieved in retrieval_result.chunks:
        chunk = retrieved.chunk
        shown_text, credential_flags = redact_credentials(
            chunk.text, code=chunk.doc_type is DocumentType.CODE
        )
        block = _render_chunk(chunk, shown_text)
        # Always keep at least one chunk, even if it alone exceeds the
        # budget; an empty context is worse than an over-budget one.
        if used_chars + len(block) > char_budget and included_blocks:
            dropped += 1
            continue
        included_blocks.append(block)
        flags = tuple(
            sorted(
                flag_text(chunk.text) + credential_flags,
                key=lambda f: (f.start, f.rule_id, f.end),
            )
        )
        if flags:
            flagged.append(
                ChunkFlags(chunk.chunk_id, chunk.source_path, chunk.doc_type.value, flags)
            )
        # The ORIGINAL path is what may be cited. The text shows a sanitised
        # spelling, so citing that spelling fails validate_citations.
        included_paths.add(retrieved.chunk.source_path)
        used_chars += len(block)

    return AssembledContext(
        text="\n".join(included_blocks),
        chunks_used=len(included_blocks),
        chunks_dropped=dropped,
        not_in_corpus=False,
        allowed_source_paths=frozenset(included_paths),
        flagged=tuple(flagged),
    )


def _neutralise_evidence_tags(text: str) -> str:
    """Stop chunk text from opening or closing an evidence or memory block."""

    return _EVIDENCE_TAG_START.sub("&lt;", text)


def _attribute(value: str) -> str:
    """Make a value safe inside a double-quoted attribute of the wrapper.

    Quotes and angle brackets become entities and line breaks become spaces.
    """

    for char in _LINE_BREAKS:
        value = value.replace(char, " ")
    return value.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _render_chunk(chunk: Chunk, text: str) -> str:
    """Wrap one chunk's (already credential-redacted) text in its evidence tag.

    The text is shown as it is, except that an evidence or memory tag inside
    it has its leading "<" neutralised, so exactly one block is shown per chunk.
    """

    req_attr = (
        f' requirement_id="{_attribute(chunk.requirement_id)}"'
        if chunk.requirement_id
        else ""
    )
    return (
        f'<evidence source_path="{_attribute(chunk.source_path)}" '
        f'doc_type="{_attribute(chunk.doc_type.value)}"{req_attr}>\n'
        f"{_neutralise_evidence_tags(text)}\n"
        f"</evidence>"
    )
