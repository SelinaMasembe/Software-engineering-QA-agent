from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from models.types import Action, Confidence, EvidenceRef, ProposalSet
from orchestrator import (
    DispatchStatus,
    ExecutionContext,
    ToolDispatcher,
    ToolRegistry,
    ToolRisk,
)
from tools.read_file import ReadFileTool

CONTEXT = ExecutionContext(session_id="session-1", actor_id="dev-1", role="developer")

ALLOWED_PATH = "requirements/allowed.md"
ALLOWED_CONTENT = "The service must reject an incorrect password.\n"
GHOST_PATH = "requirements/ghost.md"  # registered, but never materialized on disk
UNREGISTERED_PATH = "requirements/never-collected.md"


def write_fixture_corpus(root: Path) -> tuple[Path, Path]:
    """Write a small, isolated register + corpus, matching the register's real
    shape (source_path/doc_type/requirement_id/original_path/...), so the
    test never depends on the real knowledge/ directory's current contents.
    """

    corpus_dir = root / "corpus"
    (corpus_dir / "requirements").mkdir(parents=True)
    (corpus_dir / "requirements" / "allowed.md").write_text(
        ALLOWED_CONTENT, encoding="utf-8"
    )

    register_path = root / "source-register.json"
    register_path.write_text(
        json.dumps(
            {
                "generated_by": "src/ingestion/tag_provenance.py",
                "document_count": 2,
                "documents": [
                    {
                        "source_path": ALLOWED_PATH,
                        "doc_type": "requirement",
                        "requirement_id": None,
                    },
                    {
                        "source_path": GHOST_PATH,
                        "doc_type": "requirement",
                        "requirement_id": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return register_path, corpus_dir


class ReadFileToolTests(unittest.TestCase):
    """Exercise the tool directly, without going through the dispatcher."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        register_path, corpus_dir = write_fixture_corpus(Path(self._tmp.name))
        self.tool = ReadFileTool(register_path=register_path, corpus_dir=corpus_dir)

    def test_satisfies_the_read_only_tool_protocol_declaration(self) -> None:
        self.assertEqual(self.tool.name, "read_file")
        self.assertIs(self.tool.risk, ToolRisk.READ_ONLY)
        self.assertIn("developer", self.tool.allowed_roles)

    def test_allowed_path_returns_its_content(self) -> None:
        arguments = self.tool.validate_arguments({"path": ALLOWED_PATH})
        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        self.assertEqual(
            output, {"status": "ok", "path": ALLOWED_PATH, "content": ALLOWED_CONTENT}
        )

    def test_path_outside_the_register_is_reported_as_not_allowed(self) -> None:
        arguments = self.tool.validate_arguments({"path": UNREGISTERED_PATH})
        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        self.assertEqual(
            output, {"status": "path_not_allowed", "path": UNREGISTERED_PATH}
        )

    def test_registered_but_missing_file_is_a_distinct_outcome(self) -> None:
        arguments = self.tool.validate_arguments({"path": GHOST_PATH})
        output = self.tool.validate_output(self.tool.run(arguments, CONTEXT))

        self.assertEqual(output, {"status": "not_found", "path": GHOST_PATH})
        # The two failure outcomes must never collapse into the same status.
        self.assertNotEqual(
            output["status"],
            self.tool.validate_output(
                self.tool.run(
                    self.tool.validate_arguments({"path": UNREGISTERED_PATH}),
                    CONTEXT,
                )
            )["status"],
        )

    def test_missing_or_blank_path_argument_is_rejected(self) -> None:
        for arguments in ({}, {"path": "   "}, {"path": 5}, {"path": "x", "extra": 1}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    self.tool.validate_arguments(arguments)


class ReadFileToolDispatcherIntegrationTests(unittest.TestCase):
    """Confirm the tool satisfies the Protocol at runtime, via the real
    ToolRegistry/ToolDispatcher -- not just structurally.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        register_path, corpus_dir = write_fixture_corpus(Path(self._tmp.name))
        tool = ReadFileTool(register_path=register_path, corpus_dir=corpus_dir)
        self.dispatcher = ToolDispatcher(ToolRegistry([tool]))

    def make_proposal(self, path: str) -> ProposalSet:
        return ProposalSet(
            action=Action.READ_FILE,
            arguments={"path": path},
            rationale="Read the cited requirement in full.",
            evidence=(EvidenceRef(source_path=path),),
            confidence=Confidence.HIGH,
        )

    def test_read_only_tool_executes_without_an_approval_gate(self) -> None:
        result = self.dispatcher.dispatch(
            self.make_proposal(ALLOWED_PATH), context=CONTEXT
        )

        self.assertTrue(result.executed)
        self.assertIs(result.status, DispatchStatus.EXECUTED)
        self.assertEqual(
            result.output,
            {"status": "ok", "path": ALLOWED_PATH, "content": ALLOWED_CONTENT},
        )

    def test_disallowed_path_still_executes_with_a_structured_result(self) -> None:
        result = self.dispatcher.dispatch(
            self.make_proposal(UNREGISTERED_PATH), context=CONTEXT
        )

        self.assertTrue(result.executed)
        self.assertEqual(
            result.output, {"status": "path_not_allowed", "path": UNREGISTERED_PATH}
        )

    def test_registered_but_missing_file_still_executes_with_a_structured_result(
        self,
    ) -> None:
        result = self.dispatcher.dispatch(self.make_proposal(GHOST_PATH), context=CONTEXT)

        self.assertTrue(result.executed)
        self.assertEqual(result.output, {"status": "not_found", "path": GHOST_PATH})


if __name__ == "__main__":
    unittest.main()
