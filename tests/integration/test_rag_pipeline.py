from __future__ import annotations

import unittest
from pathlib import Path

from rag import (
    ChunkingConfig,
    CorpusInputError,
    DocumentType,
    RetrievalConfigurationError,
    RetrievalPolicy,
    SourceDocument,
    build_retrieval_pipeline,
    chunk_document,
    load_documents_from_directory,
    tokenize,
)

CORPUS_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "member2" / "corpus"


def load_fixture_corpus() -> list[SourceDocument]:
    return load_documents_from_directory(CORPUS_ROOT)


def make_pipeline(**kwargs):
    return build_retrieval_pipeline(
        load_fixture_corpus(), corpus_version="week3-fixture", **kwargs
    )


class ChunkingTests(unittest.TestCase):
    def test_chunk_carries_source_path_and_line_numbers(self) -> None:
        document = SourceDocument(
            source_path="requirements/auth.md",
            text="First block line one.\nFirst block line two.\n\nSecond block.\n",
            doc_type=DocumentType.REQUIREMENT,
        )

        chunks = chunk_document(document)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].source_path, "requirements/auth.md")
        self.assertEqual((chunks[0].start_line, chunks[0].end_line), (1, 2))
        self.assertEqual((chunks[1].start_line, chunks[1].end_line), (4, 4))
        self.assertEqual(chunks[0].chunk_id, "requirements/auth.md#L1-L2")

    def test_requirement_id_is_extracted_from_text(self) -> None:
        document = SourceDocument(
            source_path="requirements/auth.md",
            text="REQ-AUTH-01 The service must reject an incorrect password.",
            doc_type=DocumentType.REQUIREMENT,
        )

        self.assertEqual(chunk_document(document)[0].requirement_id, "REQ-AUTH-01")

    def test_explicit_requirement_id_overrides_the_text_heuristic(self) -> None:
        document = SourceDocument(
            source_path="requirements/auth.md",
            text="REQ-AUTH-99 text that mentions another identifier.",
            doc_type=DocumentType.REQUIREMENT,
            requirement_id="REQ-AUTH-01",
        )

        self.assertEqual(chunk_document(document)[0].requirement_id, "REQ-AUTH-01")

    def test_short_block_is_kept_rather_than_discarded(self) -> None:
        document = SourceDocument(
            source_path="requirements/short.md",
            text="A first paragraph with enough text to stand alone.\n\nShort.\n",
            doc_type=DocumentType.REQUIREMENT,
        )

        chunks = chunk_document(document)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[1].text, "Short.")

    def test_requirement_heading_is_joined_to_the_text_it_introduces(self) -> None:
        document = SourceDocument(
            source_path="requirements/auth.md",
            text=(
                "REQ-AUTH-01 Reject an incorrect password\n"
                "\n"
                "The service must reject an incorrect password\n"
                "without creating a session.\n"
            ),
            doc_type=DocumentType.REQUIREMENT,
        )

        chunks = chunk_document(document)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].requirement_id, "REQ-AUTH-01")
        self.assertIn("without creating a session", chunks[0].text)

    def test_code_is_split_on_top_level_definitions(self) -> None:
        document = SourceDocument(
            source_path="src/service.py",
            text=(
                "import os\n"
                "\n"
                "\n"
                "def first():\n"
                "    return 1\n"
                "\n"
                "\n"
                "def second():\n"
                "    return 2\n"
            ),
            doc_type=DocumentType.CODE,
        )

        chunks = chunk_document(document)
        bodies = [chunk.text for chunk in chunks]

        self.assertEqual(len(chunks), 3)
        self.assertIn("import os", bodies[0])
        self.assertIn("def first", bodies[1])
        self.assertIn("def second", bodies[2])
        self.assertNotIn("def second", bodies[1])

    def test_code_chunking_survives_a_file_that_does_not_parse(self) -> None:
        document = SourceDocument(
            source_path="src/broken.py",
            text="def first(\n    return 1\n\n\ndef second():\n    return 2\n",
            doc_type=DocumentType.CODE,
        )

        self.assertGreaterEqual(len(chunk_document(document)), 2)

    def test_oversized_block_is_windowed_with_overlap(self) -> None:
        document = SourceDocument(
            source_path="logs/run.log",
            text="\n".join(f"line {number}" for number in range(1, 26)),
            doc_type=DocumentType.LOG,
        )

        chunks = chunk_document(
            document, ChunkingConfig(max_lines=10, overlap_lines=2)
        )

        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(chunks[0].end_line - chunks[0].start_line + 1, 10)
        self.assertLess(chunks[1].start_line, chunks[0].end_line + 1)

    def test_rejects_a_document_with_no_readable_text(self) -> None:
        with self.assertRaisesRegex(CorpusInputError, "no readable text"):
            chunk_document(SourceDocument(source_path="empty.md", text="   \n"))

    def test_rejects_a_duplicate_source_path(self) -> None:
        document = SourceDocument(source_path="a.md", text="Some requirement text.")

        with self.assertRaisesRegex(CorpusInputError, "Duplicate source path"):
            build_retrieval_pipeline([document, document])

    def test_rejects_invalid_chunking_configuration(self) -> None:
        with self.assertRaisesRegex(RetrievalConfigurationError, "overlap_lines"):
            ChunkingConfig(max_lines=5, overlap_lines=5).validate()


class TokenizerTests(unittest.TestCase):
    def test_identifiers_are_split_into_searchable_words(self) -> None:
        self.assertEqual(tokenize("authenticate_user"), ["authenticate", "user"])
        self.assertEqual(tokenize("authenticateUser"), ["authenticate", "user"])

    def test_stopwords_and_single_characters_are_dropped(self) -> None:
        self.assertEqual(tokenize("what is a session"), ["session"])


class RetrievalTests(unittest.TestCase):
    def test_returns_the_relevant_requirement_first(self) -> None:
        result = make_pipeline().retrieve("reject an incorrect password")

        self.assertFalse(result.not_in_corpus)
        self.assertTrue(result.chunks)
        self.assertIn("incorrect password", result.chunks[0].chunk.text)

    def test_every_returned_chunk_carries_provenance(self) -> None:
        result = make_pipeline().retrieve("account lockout after failed attempts")

        self.assertTrue(result.chunks)
        for retrieved in result.chunks:
            self.assertTrue(retrieved.chunk.source_path)
            self.assertGreaterEqual(retrieved.chunk.start_line, 1)
            self.assertGreaterEqual(
                retrieved.chunk.end_line, retrieved.chunk.start_line
            )

    def test_path_scope_restricts_results_to_one_area(self) -> None:
        result = make_pipeline().retrieve("password", path_scope="src")

        self.assertTrue(result.chunks)
        for retrieved in result.chunks:
            self.assertTrue(retrieved.chunk.source_path.startswith("src/"))

    def test_top_k_limits_the_number_of_chunks_returned(self) -> None:
        result = make_pipeline().retrieve("password", top_k=1)

        self.assertLessEqual(len(result.chunks), 1)

    def test_unanswerable_question_returns_not_in_corpus(self) -> None:
        result = make_pipeline().retrieve(
            "how do we configure kubernetes ingress certificates"
        )

        self.assertTrue(result.not_in_corpus)
        self.assertEqual(result.chunks, ())

    def test_query_with_no_meaningful_terms_returns_not_in_corpus(self) -> None:
        result = make_pipeline().retrieve("what is the and of it")

        self.assertTrue(result.not_in_corpus)
        self.assertEqual(result.candidates_considered, 0)

    def test_coverage_floor_is_the_control_for_not_in_corpus(self) -> None:
        # Two of the four terms are absent from the corpus, so the best
        # achievable coverage is 0.5. A floor either side of that flips the
        # verdict, which is the whole point of the control.
        query = "incorrect password kubernetes ingress"

        permissive = make_pipeline(
            policy=RetrievalPolicy(min_term_coverage=0.4)
        ).retrieve(query)
        strict = make_pipeline(
            policy=RetrievalPolicy(min_term_coverage=0.6)
        ).retrieve(query)

        self.assertAlmostEqual(permissive.top_term_coverage, 0.5)
        self.assertFalse(permissive.not_in_corpus)
        self.assertTrue(strict.not_in_corpus)
        self.assertAlmostEqual(strict.top_term_coverage, 0.5)

    def test_rejected_query_still_reports_why_it_was_rejected(self) -> None:
        result = make_pipeline(
            policy=RetrievalPolicy(min_term_coverage=0.99)
        ).retrieve("incorrect password kubernetes ingress")

        self.assertTrue(result.not_in_corpus)
        self.assertGreater(result.candidates_considered, 0)
        self.assertGreater(result.top_score, 0.0)

    def test_requirement_id_query_finds_its_requirement(self) -> None:
        result = make_pipeline().retrieve("REQ-AUTH-02")

        self.assertFalse(result.not_in_corpus)
        self.assertEqual(result.chunks[0].chunk.requirement_id, "REQ-AUTH-02")


class ContractTests(unittest.TestCase):
    def test_result_matches_the_search_repo_output_schema(self) -> None:
        output = make_pipeline().retrieve("incorrect password").to_search_repo_output()

        self.assertEqual(set(output), {"chunks", "not_in_corpus"})
        self.assertIsInstance(output["not_in_corpus"], bool)
        for chunk in output["chunks"]:
            self.assertLessEqual(
                set(chunk), {"text", "source_path", "requirement_id"}
            )
            self.assertIn("text", chunk)
            self.assertIn("source_path", chunk)

    def test_not_in_corpus_output_carries_no_chunks(self) -> None:
        output = make_pipeline().retrieve("unrelated kubernetes topic").to_search_repo_output()

        self.assertTrue(output["not_in_corpus"])
        self.assertEqual(output["chunks"], [])

    def test_trace_record_excludes_chunk_text(self) -> None:
        record = make_pipeline().retrieve("incorrect password").to_trace_record()

        self.assertIn("corpus_fingerprint", record)
        self.assertIn("returned", record)
        for entry in record["returned"]:
            self.assertNotIn("text", entry)
            self.assertIn("chunk_id", entry)

    def test_fingerprint_is_stable_and_changes_with_the_corpus(self) -> None:
        first = make_pipeline().manifest
        second = make_pipeline().manifest

        self.assertEqual(first.corpus_fingerprint, second.corpus_fingerprint)
        self.assertEqual(first.corpus_version, "week3-fixture")

        extended = build_retrieval_pipeline(
            load_fixture_corpus()
            + [SourceDocument(source_path="extra.md", text="An added requirement.")]
        )
        self.assertNotEqual(
            first.corpus_fingerprint, extended.manifest.corpus_fingerprint
        )

    def test_manifest_counts_documents_and_chunks(self) -> None:
        manifest = make_pipeline().manifest

        self.assertEqual(manifest.document_count, 3)
        self.assertGreater(manifest.chunk_count, manifest.document_count)


if __name__ == "__main__":
    unittest.main()
