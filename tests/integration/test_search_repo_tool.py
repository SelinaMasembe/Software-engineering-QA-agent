from __future__ import annotations

import unittest

from models.types import Action, Confidence, EvidenceRef, ProposalSet
from orchestrator import (
    DispatchStatus,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRisk,
)
from rag import DocumentType, RetrievalPolicy, SourceDocument, build_retrieval_pipeline
from tools.search_repo import SearchRepoTool

CONTEXT = ExecutionContext(session_id="session-1", actor_id="dev-1", role="developer")


def make_pipeline(**kwargs):
    documents = [
        SourceDocument(
            source_path="requirements/auth.md",
            text="REQ-AUTH-01 The service must reject an incorrect password.",
            doc_type=DocumentType.REQUIREMENT,
            requirement_id="REQ-AUTH-01",
        ),
        SourceDocument(
            source_path="src/login_service.py",
            text=(
                "def authenticate_user(username, password):\n"
                "    return check_password(username, password)\n"
            ),
            doc_type=DocumentType.CODE,
        ),
    ]
    return build_retrieval_pipeline(documents, corpus_version="search-repo-fixture", **kwargs)


class SearchRepoToolTests(unittest.TestCase):
    """Exercise the tool directly, without going through the dispatcher."""

    def setUp(self) -> None:
        self.tool = SearchRepoTool(make_pipeline())

    def test_satisfies_the_read_only_tool_protocol_declaration(self) -> None:
        self.assertEqual(self.tool.name, "search_repo")
        self.assertIs(self.tool.risk, ToolRisk.READ_ONLY)
        self.assertIn("developer", self.tool.allowed_roles)

    def test_relevant_query_returns_chunks_with_doc_type(self) -> None:
        arguments = self.tool.validate_arguments({"query": "incorrect password"})
        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        self.assertFalse(output["not_in_corpus"])
        self.assertTrue(output["chunks"])
        first = output["chunks"][0]
        self.assertEqual(first["source_path"], "requirements/auth.md")
        self.assertEqual(first["doc_type"], "requirement")
        self.assertEqual(first["requirement_id"], "REQ-AUTH-01")
        self.assertIn("incorrect password", first["text"])

    def test_doc_type_is_preserved_for_a_code_chunk_too(self) -> None:
        arguments = self.tool.validate_arguments({"query": "authenticate_user"})
        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        self.assertTrue(output["chunks"])
        self.assertEqual(output["chunks"][0]["doc_type"], "code")
        self.assertNotIn("requirement_id", output["chunks"][0])

    def test_unanswerable_query_returns_not_in_corpus(self) -> None:
        arguments = self.tool.validate_arguments(
            {"query": "how do we configure kubernetes ingress certificates"}
        )
        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        self.assertTrue(output["not_in_corpus"])
        self.assertEqual(output["chunks"], [])

    def test_path_scope_is_forwarded_to_the_pipeline(self) -> None:
        arguments = self.tool.validate_arguments(
            {"query": "password", "path_scope": "src"}
        )
        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        for chunk in output["chunks"]:
            self.assertTrue(chunk["source_path"].startswith("src/"))

    def test_top_k_limits_results(self) -> None:
        tool = SearchRepoTool(make_pipeline(policy=RetrievalPolicy(top_k=5)))
        arguments = tool.validate_arguments({"query": "password", "top_k": 1})
        output = tool.validate_output(tool.run(arguments, CONTEXT))

        self.assertLessEqual(len(output["chunks"]), 1)

    def test_missing_or_blank_query_is_rejected(self) -> None:
        for arguments in ({}, {"query": "   "}, {"query": 5}, {"query": "x", "extra": 1}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    self.tool.validate_arguments(arguments)

    def test_non_positive_top_k_is_rejected(self) -> None:
        for top_k in (0, -1, "5", True):
            with self.subTest(top_k=top_k):
                with self.assertRaises(ValueError):
                    self.tool.validate_arguments({"query": "password", "top_k": top_k})


class SearchRepoToolDispatcherIntegrationTests(unittest.TestCase):
    """Confirm the tool satisfies the Protocol at runtime, via the real
    ToolRegistry/ToolDispatcher -- not just structurally.
    """

    def setUp(self) -> None:
        tool = SearchRepoTool(make_pipeline())
        self.dispatcher = ToolDispatcher(ToolRegistry([tool]))

    def make_proposal(self, query: str, **arguments) -> ProposalSet:
        return ProposalSet(
            action=Action.SEARCH_REPO,
            arguments={"query": query, **arguments},
            rationale="Find evidence for the login requirement.",
            evidence=(EvidenceRef(source_path="requirements/auth.md"),),
            confidence=Confidence.HIGH,
        )

    def test_read_only_tool_executes_without_an_approval_gate(self) -> None:
        result = self.dispatcher.dispatch(
            self.make_proposal("incorrect password"), context=CONTEXT
        )

        self.assertTrue(result.executed)
        self.assertIs(result.status, DispatchStatus.EXECUTED)
        self.assertFalse(result.output["not_in_corpus"])
        self.assertEqual(result.output["chunks"][0]["doc_type"], "requirement")

    def test_unanswerable_query_still_executes_with_not_in_corpus(self) -> None:
        result = self.dispatcher.dispatch(
            self.make_proposal("kubernetes ingress certificates"), context=CONTEXT
        )

        self.assertTrue(result.executed)
        self.assertTrue(result.output["not_in_corpus"])
        self.assertEqual(result.output["chunks"], [])


if __name__ == "__main__":
    unittest.main()
