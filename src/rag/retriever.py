"""Deterministic lexical retrieval over a chunked corpus.

Retrieval is scored with BM25 over locally built statistics. Nothing here calls
an external service, so the same corpus and query always produce the same
ranking, which is what makes Member 4's evaluation set reproducible and keeps
repository text from leaving the project (risk R9).

``Retriever`` is the seam. An embedding-backed implementation can replace this
one without the pipeline, the tools, or the evaluation harness changing.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol, Sequence

from .chunking import (
    REQUIREMENT_ID_PATTERN,
    Chunk,
    RetrievalConfigurationError,
)

_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]*|\d+")
_IDENTIFIER_PART_PATTERN = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")

# Deliberately small. An aggressive stop list hurts code search, where words
# such as "return" or "if" carry real meaning.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do",
        "does", "for", "from", "has", "have", "how", "in", "is", "it", "its",
        "of", "on", "or", "should", "that", "the", "their", "then", "there",
        "this", "to", "was", "were", "what", "when", "which", "who", "why",
        "will", "with", "would",
    }
)

MIN_TOKEN_LENGTH = 2


def tokenize(text: str) -> list[str]:
    """Split text into comparable terms, breaking identifiers into words.

    ``authenticate_user`` and ``authenticateUser`` both reduce to
    ``["authenticate", "user"]`` so a natural-language question can match a
    code identifier.
    """

    tokens: list[str] = []
    for raw in _TOKEN_PATTERN.findall(text):
        for part in _IDENTIFIER_PART_PATTERN.findall(raw) or [raw]:
            term = part.lower()
            if len(term) < MIN_TOKEN_LENGTH or term in STOPWORDS:
                continue
            tokens.append(term)
    return tokens


@dataclass(frozen=True)
class RetrievedChunk:
    """One scored chunk, with the evidence for why it was returned."""

    chunk: Chunk
    score: float
    term_coverage: float
    matched_terms: tuple[str, ...]


class Retriever(Protocol):
    """Interface implemented by every retrieval backend."""

    def search(
        self,
        query: str,
        *,
        path_scope: str | None = None,
        limit: int = 5,
    ) -> list[RetrievedChunk]:
        """Return the best chunks for a query, highest score first."""


class LexicalRetriever:
    """BM25 ranking over an in-memory postings list."""

    def __init__(
        self,
        chunks: Sequence[Chunk],
        *,
        k1: float = 1.5,
        b: float = 0.75,
        requirement_id_boost: float = 1.5,
    ) -> None:
        if k1 <= 0:
            raise RetrievalConfigurationError("BM25 k1 must be greater than zero.")
        if not 0.0 <= b <= 1.0:
            raise RetrievalConfigurationError("BM25 b must be between 0 and 1.")
        if requirement_id_boost < 1.0:
            raise RetrievalConfigurationError(
                "Requirement-ID boost must be at least 1.0."
            )

        self.k1 = k1
        self.b = b
        self.requirement_id_boost = requirement_id_boost
        self.chunks = tuple(chunks)

        self._term_frequencies: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._document_frequency: Counter[str] = Counter()
        for chunk in self.chunks:
            counts = Counter(tokenize(chunk.text))
            self._term_frequencies.append(counts)
            self._lengths.append(sum(counts.values()))
            self._document_frequency.update(counts.keys())

        total_length = sum(self._lengths)
        self._average_length = total_length / len(self.chunks) if self.chunks else 0.0

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    def search(
        self,
        query: str,
        *,
        path_scope: str | None = None,
        limit: int = 5,
    ) -> list[RetrievedChunk]:
        if limit <= 0:
            raise RetrievalConfigurationError("limit must be greater than zero.")

        query_terms = tokenize(query)
        if not query_terms or not self.chunks:
            return []

        unique_terms = set(query_terms)
        wanted_ids = set(REQUIREMENT_ID_PATTERN.findall(query))
        candidates = [
            index
            for index in range(len(self.chunks))
            if _in_scope(self.chunks[index].source_path, path_scope)
        ]

        results: list[RetrievedChunk] = []
        for index in candidates:
            counts = self._term_frequencies[index]
            matched = sorted(term for term in unique_terms if counts[term])
            chunk = self.chunks[index]
            id_match = bool(wanted_ids) and chunk.requirement_id in wanted_ids
            if not matched and not id_match:
                continue

            score = sum(self._term_score(term, counts, index) for term in unique_terms)
            if id_match:
                score = max(score, 1.0) * self.requirement_id_boost
            if score <= 0.0:
                continue

            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=round(score, 6),
                    term_coverage=round(len(matched) / len(unique_terms), 6),
                    matched_terms=tuple(matched),
                )
            )

        results.sort(key=lambda item: (-item.score, item.chunk.chunk_id))
        return results[:limit]

    def _term_score(self, term: str, counts: Counter[str], index: int) -> float:
        frequency = counts[term]
        if not frequency:
            return 0.0

        document_frequency = self._document_frequency[term]
        idf = math.log(
            1.0
            + (len(self.chunks) - document_frequency + 0.5)
            / (document_frequency + 0.5)
        )
        length_ratio = (
            self._lengths[index] / self._average_length if self._average_length else 1.0
        )
        denominator = frequency + self.k1 * (1.0 - self.b + self.b * length_ratio)
        return idf * (frequency * (self.k1 + 1.0)) / denominator


def _in_scope(source_path: str, path_scope: str | None) -> bool:
    if not path_scope:
        return True
    scope = path_scope.strip().rstrip("/")
    return source_path == scope or source_path.startswith(f"{scope}/")
