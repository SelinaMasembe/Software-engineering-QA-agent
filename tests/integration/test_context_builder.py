from __future__ import annotations

import unittest
from pathlib import Path

from rag import (
    AssembledContext,
    Chunk,
    DocumentType,
    IndexManifest,
    RetrievalConfigurationError,
    RetrievalResult,
    RetrievedChunk,
    build_context,
    build_retrieval_pipeline,
    load_documents_from_directory,
)
from rag.context_builder import NO_EVIDENCE_MESSAGE

CORPUS_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "member2" / "corpus"

_MANIFEST = IndexManifest(
    corpus_version="test",
    corpus_fingerprint="deadbeef",
    document_count=1,
    chunk_count=1,
)


def load_fixture_corpus():
    return load_documents_from_directory(CORPUS_ROOT)


def make_pipeline(**kwargs):
    return build_retrieval_pipeline(
        load_fixture_corpus(), corpus_version="week3-fixture", **kwargs
    )


def make_retrieved_chunk(**overrides) -> RetrievedChunk:
    chunk_kwargs = dict(
        chunk_id="fixture.md#L1-L1",
        text="Fixture chunk text.",
        source_path="fixture.md",
        doc_type=DocumentType.REQUIREMENT,
        start_line=1,
        end_line=1,
        requirement_id=None,
    )
    chunk_kwargs.update(overrides)
    return RetrievedChunk(
        chunk=Chunk(**chunk_kwargs), score=1.0, term_coverage=1.0, matched_terms=()
    )


def make_result(chunks: tuple[RetrievedChunk, ...], **overrides) -> RetrievalResult:
    kwargs = dict(
        query="fixture query",
        chunks=chunks,
        not_in_corpus=False,
        manifest=_MANIFEST,
        candidates_considered=len(chunks),
        top_score=1.0,
        top_term_coverage=1.0,
        latency_ms=0,
    )
    kwargs.update(overrides)
    return RetrievalResult(**kwargs)


class BuildContextEndToEndTests(unittest.TestCase):
    def test_relevant_query_produces_verbatim_citable_evidence(self) -> None:
        result = make_pipeline().retrieve("reject an incorrect password")

        context = build_context(result)

        self.assertIsInstance(context, AssembledContext)
        self.assertFalse(context.not_in_corpus)
        self.assertGreater(context.chunks_used, 0)
        self.assertEqual(context.chunks_dropped, 0)
        for retrieved in result.chunks:
            self.assertIn(
                f'source_path="{retrieved.chunk.source_path}"', context.text
            )
            self.assertIn(retrieved.chunk.source_path, context.allowed_source_paths)

    def test_unanswerable_query_returns_not_in_corpus_message(self) -> None:
        result = make_pipeline().retrieve(
            "how do we configure kubernetes ingress certificates"
        )

        context = build_context(result)

        self.assertTrue(context.not_in_corpus)
        self.assertEqual(context.text, NO_EVIDENCE_MESSAGE)
        self.assertEqual(context.chunks_used, 0)
        self.assertEqual(context.allowed_source_paths, frozenset())


class BuildContextBudgetTests(unittest.TestCase):
    def test_lowest_ranked_whole_chunks_are_dropped_over_budget(self) -> None:
        big = make_retrieved_chunk(
            chunk_id="big.md#L1-L1", source_path="big.md", text="x" * 50
        )
        small = make_retrieved_chunk(
            chunk_id="small.md#L1-L1", source_path="small.md", text="small"
        )
        result = make_result((big, small))

        context = build_context(result, char_budget=60)

        self.assertEqual(context.chunks_used, 1)
        self.assertEqual(context.chunks_dropped, 1)
        self.assertIn("big.md", context.text)
        self.assertNotIn("small.md", context.text)
        self.assertEqual(context.allowed_source_paths, frozenset({"big.md"}))

    def test_first_chunk_is_kept_even_alone_over_budget(self) -> None:
        oversized = make_retrieved_chunk(text="x" * 500)
        result = make_result((oversized,))

        context = build_context(result, char_budget=10)

        self.assertEqual(context.chunks_used, 1)
        self.assertEqual(context.chunks_dropped, 0)

    def test_non_positive_budget_is_rejected(self) -> None:
        result = make_result((make_retrieved_chunk(),))

        with self.assertRaisesRegex(RetrievalConfigurationError, "char_budget"):
            build_context(result, char_budget=0)


class RenderChunkTests(unittest.TestCase):
    def test_requirement_id_attribute_is_included_when_present(self) -> None:
        chunk = make_retrieved_chunk(requirement_id="REQ-AUTH-01")
        context = build_context(make_result((chunk,)))

        self.assertIn('requirement_id="REQ-AUTH-01"', context.text)

    def test_requirement_id_attribute_is_omitted_when_absent(self) -> None:
        chunk = make_retrieved_chunk(requirement_id=None)
        context = build_context(make_result((chunk,)))

        self.assertNotIn("requirement_id=", context.text)


if __name__ == "__main__":
    unittest.main()
