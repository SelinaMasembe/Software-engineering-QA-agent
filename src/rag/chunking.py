"""Corpus contracts and boundary-aware chunking for the retrieval pipeline.

This module owns the shape of a corpus document, the shape of a chunk, and the
rules that split one into the other. Provenance travels with every chunk so a
later proposal can cite the exact file and lines it was derived from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class RetrievalError(Exception):
    """Base class for retrieval errors safe to show to an application user."""


class CorpusInputError(RetrievalError):
    """Raised when a supplied source document cannot be indexed."""


class RetrievalConfigurationError(RetrievalError):
    """Raised when chunking or retrieval settings are invalid."""


class DocumentType(str, Enum):
    """The corpus shapes the agent reads, per the Week 1 architecture."""

    REQUIREMENT = "requirement"
    CODE = "code"
    LOG = "log"
    OTHER = "other"


# Matches REQ-AUTH-01, US-11, and similar identifiers. This is a heuristic used
# only when Member 1's provenance tagger does not supply an explicit ID; an ID
# set on the document always wins.
REQUIREMENT_ID_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,7}(?:-[A-Z0-9]{1,8})+\b")

_CODE_UNIT_PATTERN = re.compile(r"(?:async\s+def|def|class)\s+\w")
_LOG_SEPARATOR_PATTERN = re.compile(r"^\s*(?:={3,}|-{3,}|_{3,})")
_DECORATOR_OR_COMMENT_PATTERN = re.compile(r"^\s*(?:@|#)")


@dataclass(frozen=True)
class SourceDocument:
    """One provenance-tagged corpus file.

    This is the contract Member 1's ``tag_provenance.py`` fills and the
    retrieval pipeline consumes. The pipeline never reads the repository by
    itself, so the corpus stays a single owned input.
    """

    source_path: str
    text: str
    doc_type: DocumentType = DocumentType.OTHER
    requirement_id: str | None = None

    def validate(self) -> None:
        if not self.source_path.strip():
            raise CorpusInputError("Source path must not be empty.")
        if not self.text.strip():
            raise CorpusInputError(
                f"Source document has no readable text: {self.source_path}"
            )
        if not isinstance(self.doc_type, DocumentType):
            raise CorpusInputError(
                f"Unknown document type for {self.source_path}: {self.doc_type!r}"
            )


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage, carrying the provenance of its source."""

    chunk_id: str
    text: str
    source_path: str
    doc_type: DocumentType
    start_line: int
    end_line: int
    requirement_id: str | None = None


@dataclass(frozen=True)
class ChunkingConfig:
    """Size limits applied after a document is split on its own boundaries.

    ``heading_max_lines`` sets how short a prose block must be to count as a
    heading that belongs with the text underneath it. No chunk is ever dropped
    for being short, so a one-line requirement keeps its own provenance.
    """

    max_lines: int = 40
    overlap_lines: int = 5
    heading_max_lines: int = 1

    def validate(self) -> None:
        if self.max_lines <= 0:
            raise RetrievalConfigurationError("max_lines must be greater than zero.")
        if self.overlap_lines < 0:
            raise RetrievalConfigurationError("overlap_lines must not be negative.")
        if self.overlap_lines >= self.max_lines:
            raise RetrievalConfigurationError(
                "overlap_lines must be smaller than max_lines."
            )
        if self.heading_max_lines < 0:
            raise RetrievalConfigurationError(
                "heading_max_lines must not be negative."
            )


def chunk_document(
    document: SourceDocument,
    config: ChunkingConfig | None = None,
) -> list[Chunk]:
    """Split one document on its natural boundaries, then enforce size limits."""

    document.validate()
    config = config or ChunkingConfig()
    config.validate()

    lines = document.text.splitlines()
    if document.doc_type is DocumentType.CODE:
        ranges = _code_ranges(lines)
    elif document.doc_type is DocumentType.LOG:
        ranges = _log_ranges(lines)
    else:
        ranges = _attach_headings(_paragraph_ranges(lines), config)

    sized: list[tuple[int, int]] = []
    for start, end in ranges:
        sized.extend(_apply_size_limit(start, end, config))

    chunks: list[Chunk] = []
    for start, end in sized:
        text = "\n".join(lines[start : end + 1]).strip("\n")
        if not any(character.isalnum() for character in text):
            continue
        chunks.append(
            Chunk(
                chunk_id=f"{document.source_path}#L{start + 1}-L{end + 1}",
                text=text,
                source_path=document.source_path,
                doc_type=document.doc_type,
                start_line=start + 1,
                end_line=end + 1,
                requirement_id=document.requirement_id or _find_requirement_id(text),
            )
        )

    if not chunks:
        raise CorpusInputError(
            f"Document produced no usable chunks: {document.source_path}"
        )
    return chunks


def chunk_documents(
    documents: list[SourceDocument] | tuple[SourceDocument, ...],
    config: ChunkingConfig | None = None,
) -> list[Chunk]:
    """Chunk a whole corpus, preserving the order documents were supplied in."""

    config = config or ChunkingConfig()
    chunks: list[Chunk] = []
    seen_paths: set[str] = set()
    for document in documents:
        if document.source_path in seen_paths:
            raise CorpusInputError(
                f"Duplicate source path in corpus: {document.source_path}"
            )
        seen_paths.add(document.source_path)
        chunks.extend(chunk_document(document, config))
    return chunks


def _attach_headings(
    ranges: list[tuple[int, int]],
    config: ChunkingConfig,
) -> list[tuple[int, int]]:
    """Join a short prose block to the longer block it introduces.

    In a requirements document the identifier usually sits on its own line above
    the text it governs. Merging the two keeps ``REQ-AUTH-01`` in the same chunk
    as the behaviour it describes, so a retrieved passage can still be cited.
    """

    if config.heading_max_lines <= 0:
        return ranges

    merged: list[tuple[int, int]] = []
    index = 0
    while index < len(ranges):
        start, end = ranges[index]
        is_heading = (end - start + 1) <= config.heading_max_lines
        has_body = index + 1 < len(ranges)
        if is_heading and has_body:
            next_start, next_end = ranges[index + 1]
            if (next_end - next_start + 1) > config.heading_max_lines:
                merged.append((start, next_end))
                index += 2
                continue
        merged.append((start, end))
        index += 1
    return merged


def _find_requirement_id(text: str) -> str | None:
    match = REQUIREMENT_ID_PATTERN.search(text)
    return match.group(0) if match else None


def _paragraph_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Group blank-line-separated blocks, which suits prose requirements."""

    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip():
            if start is None:
                start = index
        elif start is not None:
            ranges.append((start, index - 1))
            start = None
    if start is not None:
        ranges.append((start, len(lines) - 1))
    return ranges or [(0, max(len(lines) - 1, 0))]


def _code_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Split at top-level definitions without requiring the file to parse.

    A regex on unindented ``def``/``class`` lines is used rather than ``ast`` so
    that a syntactically broken file still produces usable chunks instead of an
    ingestion failure.
    """

    starts: list[int] = []
    for index, line in enumerate(lines):
        if not line or line[0].isspace():
            continue
        if _CODE_UNIT_PATTERN.match(line):
            starts.append(_claim_preceding_context(lines, index))
    return _ranges_from_starts(starts, len(lines))


def _claim_preceding_context(lines: list[str], index: int) -> int:
    """Attach decorators and the comment block directly above a definition."""

    start = index
    while start > 0 and _DECORATOR_OR_COMMENT_PATTERN.match(lines[start - 1] or ""):
        start -= 1
    return start


def _log_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Split at separator rules, then on blank lines inside each section."""

    starts = [
        index for index, line in enumerate(lines) if _LOG_SEPARATOR_PATTERN.match(line)
    ]
    sections = _ranges_from_starts(starts, len(lines))

    ranges: list[tuple[int, int]] = []
    for start, end in sections:
        for offset_start, offset_end in _paragraph_ranges(lines[start : end + 1]):
            ranges.append((start + offset_start, start + offset_end))
    return ranges


def _ranges_from_starts(starts: list[int], line_count: int) -> list[tuple[int, int]]:
    if line_count == 0:
        return [(0, 0)]
    boundaries = sorted(set(starts))
    if not boundaries or boundaries[0] != 0:
        boundaries.insert(0, 0)

    ranges: list[tuple[int, int]] = []
    for position, start in enumerate(boundaries):
        is_last = position + 1 == len(boundaries)
        end = line_count - 1 if is_last else boundaries[position + 1] - 1
        if end >= start:
            ranges.append((start, end))
    return ranges


def _apply_size_limit(
    start: int,
    end: int,
    config: ChunkingConfig,
) -> list[tuple[int, int]]:
    """Window any range that exceeds the configured maximum length."""

    length = end - start + 1
    if length <= config.max_lines:
        return [(start, end)]

    step = config.max_lines - config.overlap_lines
    windows: list[tuple[int, int]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + config.max_lines - 1, end)
        windows.append((cursor, window_end))
        if window_end == end:
            break
        cursor += step
    return windows
