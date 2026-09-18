"""Week 3 retrieval pipeline: read, chunk, index, and retrieve with provenance.

This is the Member 2 integration deliverable. It wires Member 1's corpus
documents through chunking and a retrieval backend, and decides deterministically
whether a query is answerable from the corpus at all.

The ``not_in_corpus`` decision is made here, in ordinary code, never by the
model. Member 3's context builder decides what the model is *told* when the flag
is set; this module only decides whether it is true.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

from .chunking import (
    Chunk,
    ChunkingConfig,
    CorpusInputError,
    DocumentType,
    RetrievalConfigurationError,
    RetrievalError,
    SourceDocument,
    chunk_documents,
)
from .retriever import LexicalRetriever, RetrievedChunk, Retriever, tokenize


@dataclass(frozen=True)
class RetrievalPolicy:
    """The deterministic rule that decides whether an answer exists.

    A query is answerable when at least ``min_matching_chunks`` chunks clear both
    floors. ``min_term_coverage`` is the primary control: it asks what share of
    the question's meaningful terms a passage actually contains, which stays
    comparable across corpora in a way that a raw BM25 score does not.
    """

    top_k: int = 5
    min_term_coverage: float = 0.34
    min_score: float = 0.0
    min_matching_chunks: int = 1

    def validate(self) -> None:
        if self.top_k <= 0:
            raise RetrievalConfigurationError("top_k must be greater than zero.")
        if not 0.0 <= self.min_term_coverage <= 1.0:
            raise RetrievalConfigurationError(
                "min_term_coverage must be between 0 and 1."
            )
        if self.min_score < 0.0:
            raise RetrievalConfigurationError("min_score must not be negative.")
        if self.min_matching_chunks <= 0:
            raise RetrievalConfigurationError(
                "min_matching_chunks must be greater than zero."
            )


@dataclass(frozen=True)
class IndexManifest:
    """Identifies exactly which corpus state produced a set of results.

    Architecture principle P4 requires a frozen corpus so the evaluation set is
    reproducible. The fingerprint makes that checkable rather than assumed.
    """

    corpus_version: str
    corpus_fingerprint: str
    document_count: int
    chunk_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus_version": self.corpus_version,
            "corpus_fingerprint": self.corpus_fingerprint,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
        }


@dataclass(frozen=True)
class RetrievalResult:
    """Retrieved evidence plus the numbers behind the not-in-corpus decision."""

    query: str
    chunks: tuple[RetrievedChunk, ...]
    not_in_corpus: bool
    manifest: IndexManifest
    candidates_considered: int
    top_score: float
    top_term_coverage: float
    latency_ms: int
    path_scope: str | None = None

    def to_search_repo_output(self) -> dict[str, Any]:
        """Return the exact ``search_repo`` output shape from the tool contract.

        Member 3's Week 4 tool wraps this rather than reshaping the result.
        """

        chunks: list[dict[str, Any]] = []
        for retrieved in self.chunks:
            entry: dict[str, Any] = {
                "text": retrieved.chunk.text,
                "source_path": retrieved.chunk.source_path,
            }
            if retrieved.chunk.requirement_id:
                entry["requirement_id"] = retrieved.chunk.requirement_id
            chunks.append(entry)
        return {"chunks": chunks, "not_in_corpus": self.not_in_corpus}

    def to_trace_record(self) -> dict[str, Any]:
        """Return a sanitized record of the retrieval step for the trace store.

        Chunk text is deliberately excluded; identifiers and scores are enough to
        reconstruct a decision without copying corpus content into a log.
        """

        return {
            "query": self.query,
            "path_scope": self.path_scope,
            "not_in_corpus": self.not_in_corpus,
            "candidates_considered": self.candidates_considered,
            "top_score": self.top_score,
            "top_term_coverage": self.top_term_coverage,
            "latency_ms": self.latency_ms,
            "corpus_version": self.manifest.corpus_version,
            "corpus_fingerprint": self.manifest.corpus_fingerprint,
            "returned": [
                {
                    "chunk_id": retrieved.chunk.chunk_id,
                    "source_path": retrieved.chunk.source_path,
                    "requirement_id": retrieved.chunk.requirement_id,
                    "score": retrieved.score,
                    "term_coverage": retrieved.term_coverage,
                    "matched_terms": list(retrieved.matched_terms),
                }
                for retrieved in self.chunks
            ],
        }


class RetrievalPipeline:
    """Read, chunk, index, and retrieve over one frozen corpus."""

    def __init__(
        self,
        documents: Sequence[SourceDocument],
        *,
        policy: RetrievalPolicy | None = None,
        chunking: ChunkingConfig | None = None,
        corpus_version: str = "unversioned",
        retriever_factory: Any = LexicalRetriever,
    ) -> None:
        if not documents:
            raise CorpusInputError("The corpus must contain at least one document.")

        self.policy = policy or RetrievalPolicy()
        self.policy.validate()
        self.chunking = chunking or ChunkingConfig()
        self.chunking.validate()

        self.documents: tuple[SourceDocument, ...] = tuple(documents)
        self.chunks: tuple[Chunk, ...] = tuple(
            chunk_documents(self.documents, self.chunking)
        )
        self.retriever: Retriever = retriever_factory(self.chunks)
        self.manifest = IndexManifest(
            corpus_version=corpus_version,
            corpus_fingerprint=_fingerprint(self.documents),
            document_count=len(self.documents),
            chunk_count=len(self.chunks),
        )

    def retrieve(
        self,
        query: str,
        *,
        path_scope: str | None = None,
        top_k: int | None = None,
    ) -> RetrievalResult:
        """Return the best evidence for a query, or an explicit not-in-corpus."""

        if not isinstance(query, str):
            raise RetrievalError("Query must be a string.")

        limit = top_k if top_k is not None else self.policy.top_k
        if limit <= 0:
            raise RetrievalConfigurationError("top_k must be greater than zero.")

        started = perf_counter()
        if not tokenize(query):
            return self._empty_result(query, path_scope, started)

        candidates = self.retriever.search(
            query, path_scope=path_scope, limit=max(limit, self.policy.top_k)
        )
        if not candidates:
            return self._empty_result(query, path_scope, started)

        accepted = [
            candidate
            for candidate in candidates
            if candidate.term_coverage >= self.policy.min_term_coverage
            and candidate.score >= self.policy.min_score
        ][:limit]

        not_in_corpus = len(accepted) < self.policy.min_matching_chunks
        return RetrievalResult(
            query=query,
            chunks=() if not_in_corpus else tuple(accepted),
            not_in_corpus=not_in_corpus,
            manifest=self.manifest,
            candidates_considered=len(candidates),
            top_score=candidates[0].score,
            top_term_coverage=candidates[0].term_coverage,
            latency_ms=_elapsed_ms(started),
            path_scope=path_scope,
        )

    def _empty_result(
        self,
        query: str,
        path_scope: str | None,
        started: float,
    ) -> RetrievalResult:
        return RetrievalResult(
            query=query,
            chunks=(),
            not_in_corpus=True,
            manifest=self.manifest,
            candidates_considered=0,
            top_score=0.0,
            top_term_coverage=0.0,
            latency_ms=_elapsed_ms(started),
            path_scope=path_scope,
        )


def build_retrieval_pipeline(
    documents: Sequence[SourceDocument],
    *,
    policy: RetrievalPolicy | None = None,
    chunking: ChunkingConfig | None = None,
    corpus_version: str = "unversioned",
) -> RetrievalPipeline:
    """Build an indexed pipeline from a provenance-tagged corpus.

    This is the stable entry point for Member 3's context builder and Member 4's
    fifteen-case evaluation harness.
    """

    return RetrievalPipeline(
        documents,
        policy=policy,
        chunking=chunking,
        corpus_version=corpus_version,
    )


# --------------------------------------------------------------------------
# Development corpus loader.
#
# Member 1 owns corpus collection and provenance tagging in
# src/ingestion/tag_provenance.py. This loader exists only so the pipeline can
# be built and tested before that lands, in the same way the Week 2 smoke runner
# stood in for Member 5's configuration loader. It is not the corpus register.
# --------------------------------------------------------------------------

_DEFAULT_TYPE_BY_SUFFIX = {
    ".py": DocumentType.CODE,
    ".js": DocumentType.CODE,
    ".ts": DocumentType.CODE,
    ".log": DocumentType.LOG,
    ".md": DocumentType.REQUIREMENT,
    ".txt": DocumentType.REQUIREMENT,
}


def load_documents_from_directory(
    root: str | Path,
    *,
    type_by_suffix: dict[str, DocumentType] | None = None,
) -> list[SourceDocument]:
    """Read a directory into source documents, inferring type from extension."""

    root_path = Path(root)
    if not root_path.is_dir():
        raise CorpusInputError(f"Corpus directory does not exist: {root_path}")

    mapping = type_by_suffix or _DEFAULT_TYPE_BY_SUFFIX
    documents: list[SourceDocument] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not text.strip():
            continue
        documents.append(
            SourceDocument(
                source_path=path.relative_to(root_path).as_posix(),
                text=text,
                doc_type=mapping.get(path.suffix, DocumentType.OTHER),
            )
        )

    if not documents:
        raise CorpusInputError(f"No readable documents found under {root_path}")
    return documents


def _fingerprint(documents: Sequence[SourceDocument]) -> str:
    digest = hashlib.sha256()
    for document in sorted(documents, key=lambda item: item.source_path):
        content = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
        digest.update(f"{document.source_path}\0{content}\n".encode("utf-8"))
    return digest.hexdigest()[:16]


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1_000)
