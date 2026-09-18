"""Retrieval boundary for the Software-Engineering QA Agent.

Other modules import from ``rag`` rather than from the files below, so the
internal split between chunking, scoring, and the pipeline can change without
breaking Member 3's context builder or Member 4's evaluation harness.

Only the retrieval surface is re-exported here. The Week 2 proposal pipeline
that also lives in this package stays available as ``rag.pipeline``.
"""

from .chunking import (
    Chunk,
    ChunkingConfig,
    CorpusInputError,
    DocumentType,
    RetrievalConfigurationError,
    RetrievalError,
    SourceDocument,
    chunk_document,
    chunk_documents,
)
from .retrieval import (
    IndexManifest,
    RetrievalPipeline,
    RetrievalPolicy,
    RetrievalResult,
    build_retrieval_pipeline,
    load_documents_from_directory,
)
from .retriever import (
    LexicalRetriever,
    RetrievedChunk,
    Retriever,
    tokenize,
)

__all__ = [
    "Chunk",
    "ChunkingConfig",
    "CorpusInputError",
    "DocumentType",
    "IndexManifest",
    "LexicalRetriever",
    "RetrievalConfigurationError",
    "RetrievalError",
    "RetrievalPipeline",
    "RetrievalPolicy",
    "RetrievalResult",
    "RetrievedChunk",
    "Retriever",
    "SourceDocument",
    "build_retrieval_pipeline",
    "chunk_document",
    "chunk_documents",
    "load_documents_from_directory",
    "tokenize",
]
