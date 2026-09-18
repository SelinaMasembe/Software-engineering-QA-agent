"""Collect the real corpus documents the agent will read from, and tag each
one with exactly where it came from.

This is Member 1's Week 3 deliverable. It fills the contract
``src/rag/chunking.py`` already names:

    "This is the contract Member 1's ``tag_provenance.py`` fills and the
    retrieval pipeline consumes. The pipeline never reads the repository by
    itself, so the corpus stays a single owned input."

Member 2's ``load_documents_from_directory`` (in ``src/rag/retrieval.py``) is
a development stand-in that infers a document's type from its file suffix
alone and can only read plain text. It says so itself:

    "It is not the corpus register."

This script is the real thing. It works from an explicit, curated list of
real repository files rather than crawling the whole tree (so screenshots,
``.git``, and binary evidence never end up "in the corpus" by accident),
resolves every one of them against the actual working tree so a moved or
renamed file is caught immediately, and produces three things:

1.  A materialized plain-text copy of every source under
    ``knowledge/corpus/<requirement|code|log>/`` -- ``SourceDocument.text``
    has to be plain text, so a ``.docx`` (the project charter, the
    architecture write-up, the prompt specification) is extracted here, not
    left as a binary the pipeline cannot open.
2.  A machine-readable register, ``knowledge/source-register.json`` --
    one record per document, directly loadable as the ``SourceDocument``
    list ``build_retrieval_pipeline`` expects, plus the provenance fields
    the pipeline itself does not need: the file's real path in the repo, a
    SHA-256 of its extracted text, its size, and when it was collected.
3.  A human-readable register, ``knowledge/source-register.md`` -- the
    Corpus/Source Register deliverable: one table row per document, answering
    "where did this come from" for a teammate or a reviewer without them
    having to open the JSON.

Usage (from the repository root):

    PYTHONPATH=src python3 src/ingestion/tag_provenance.py

Re-running it is safe and expected: it always re-reads the curated sources
and rewrites the corpus and both registers from scratch, so the register
never drifts from the files it describes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rag.chunking import DocumentType, SourceDocument  # noqa: E402

try:
    import docx  # python-docx
except ImportError:  # pragma: no cover - exercised only when the dependency is missing
    docx = None


CORPUS_DIR = REPO_ROOT / "knowledge" / "corpus"
JSON_REGISTER_PATH = REPO_ROOT / "knowledge" / "source-register.json"
MD_REGISTER_PATH = REPO_ROOT / "knowledge" / "source-register.md"

_TYPE_DIR_NAME = {
    DocumentType.REQUIREMENT: "requirements",
    DocumentType.CODE: "code",
    DocumentType.LOG: "logs",
    DocumentType.OTHER: "other",
}


@dataclass(frozen=True)
class CuratedSource:
    """One entry in the curated list below: a real file plus why it belongs."""

    original_path: str  # repo-relative path to the real file this came from
    doc_type: DocumentType
    corpus_name: str  # filename to give the materialized plain-text copy
    collected_by: str  # who/what produced this file in the repo, for provenance
    reason: str  # why this file is in the corpus
    requirement_id: str | None = None  # only set when the WHOLE document is
    # scoped to one requirement/story (rare for our real documents, which
    # mostly span many). Left unset, per-chunk tagging in chunk_document()
    # still finds a requirement id in each individual chunk's own text --
    # that is the meaningful place to detect it, not a whole multi-page file.


# ---------------------------------------------------------------------------
# The curated corpus. Every entry names a real file that already exists in
# this repository and is owned by a real Week 1-3 deliverable -- nothing here
# is invented or placeholder content. Team-owned requirements, code, and log
# files, per the Charter's own Proposed Solution ("We will build and evaluate
# the system using our own team-owned codebase, its requirements
# documentation, and its test logs").
# ---------------------------------------------------------------------------
CURATED_SOURCES: tuple[CuratedSource, ...] = (
    # -- Requirements -------------------------------------------------------
    CuratedSource(
        "docs/requirements/Project_charter and user stories.docx",
        DocumentType.REQUIREMENT,
        "project-charter-and-user-stories.txt",
        "Member 1 (Week 1)",
        "The project charter and all twelve user stories with acceptance "
        "criteria -- the source of truth every other document traces back to.",
    ),
    CuratedSource(
        "docs/architecture/QA_Agent_Architecture_Week1.docx",
        DocumentType.REQUIREMENT,
        "qa-agent-architecture-week1.txt",
        "Member 2 (Week 1)",
        "The approved system architecture the retrieval pipeline and tool "
        "contracts are built against.",
    ),
    CuratedSource(
        "docs/architecture/Member3_AIEngineering_Deliverables.docx",
        DocumentType.REQUIREMENT,
        "ai-engineering-design-notes.txt",
        "Member 3 (Week 1)",
        "The AI engineering design notes: prompting approach, model "
        "boundaries, and the risk register (R1-R9) later cases test against.",
    ),
    CuratedSource(
        "docs/prompts/Prompt_Specification.docx",
        DocumentType.REQUIREMENT,
        "prompt-specification.txt",
        "Member 3 (Week 2)",
        "The full prompt specification behind propose_action, including the "
        "failure-behaviour contract the malformed-source-code case relies on.",
    ),
    CuratedSource(
        "docs/prompts/Model_Selection_Note.docx",
        DocumentType.REQUIREMENT,
        "model-selection-note.txt",
        "Member 3 (Week 2)",
        "The model selection rationale the ChatCompletionsClient is built "
        "against.",
    ),
    CuratedSource(
        "docs/prompts/propose_action/v1.0.md",
        DocumentType.REQUIREMENT,
        "propose-action-prompt-v1.0.md",
        "Member 3 (Week 2)",
        "First approved version of the propose_action prompt contract.",
    ),
    CuratedSource(
        "docs/prompts/propose_action/v1.1.md",
        DocumentType.REQUIREMENT,
        "propose-action-prompt-v1.1.md",
        "Member 3 (Week 2)",
        "Current approved version of the propose_action prompt contract "
        "(adds the system-prompt confidentiality clause from US-11's Week 2 "
        "amendment).",
    ),
    CuratedSource(
        "docs/requirements/week2-test-case-traceability.md",
        DocumentType.REQUIREMENT,
        "week2-test-case-traceability.md",
        "Member 1 (Week 2)",
        "Maps all ten of Member 4's evaluation cases to the user stories "
        "they exercise, including the two acceptance-criteria resolutions.",
    ),
    # -- Code -----------------------------------------------------------
    CuratedSource(
        "src/config/loader.py",
        DocumentType.CODE,
        "config_loader.py",
        "Member 5",
        "Loads and validates model configuration from the environment.",
    ),
    CuratedSource(
        "src/models/client.py",
        DocumentType.CODE,
        "models_client.py",
        "Member 2 (Week 2)",
        "The hand-rolled HTTP client that calls the model provider and "
        "translates provider failures into typed errors.",
    ),
    CuratedSource(
        "src/models/types.py",
        DocumentType.CODE,
        "models_types.py",
        "Member 1 (Week 2)",
        "The domain model: ProposalSet, TestProposal, and the traceable-"
        "citation check (validate_sources) that enforces US-8 in code.",
    ),
    CuratedSource(
        "src/prompts/loader.py",
        DocumentType.CODE,
        "prompts_loader.py",
        "Member 3 (Week 2)",
        "Loads a versioned prompt file by id and version.",
    ),
    CuratedSource(
        "src/rag/chunking.py",
        DocumentType.CODE,
        "rag_chunking.py",
        "Member 2 (Week 3)",
        "Defines the SourceDocument/Chunk contract this script fills, and "
        "the boundary-aware splitter that turns a document into chunks.",
    ),
    CuratedSource(
        "src/rag/retriever.py",
        DocumentType.CODE,
        "rag_retriever.py",
        "Member 2 (Week 3)",
        "The deterministic BM25 lexical retriever the pipeline ranks "
        "chunks with.",
    ),
    CuratedSource(
        "src/rag/retrieval.py",
        DocumentType.CODE,
        "rag_retrieval.py",
        "Member 2 (Week 3)",
        "The retrieval pipeline itself: indexes a corpus and makes the "
        "not_in_corpus decision in ordinary code, not the model.",
    ),
    CuratedSource(
        "scripts/member1_types_smoke.py",
        DocumentType.CODE,
        "member1_types_smoke.py",
        "Member 1 (Week 2)",
        "Runs the real ten evaluation cases through the domain model as a "
        "development smoke check.",
    ),
    CuratedSource(
        "scripts/member2_model_smoke.py",
        DocumentType.CODE,
        "member2_model_smoke.py",
        "Member 2 (Week 2)",
        "Sends one real, sanitized request through the model client as a "
        "live smoke check.",
    ),
    CuratedSource(
        "tests/test_prompt_harness.py",
        DocumentType.CODE,
        "test_prompt_harness.py",
        "Member 4 (Week 2)",
        "The offline harness that scores every propose_action case against "
        "its expected action, evidence, and confidence.",
    ),
    CuratedSource(
        "tests/integration/test_model_integration.py",
        DocumentType.CODE,
        "test_model_integration.py",
        "Member 2 (Week 2)",
        "Offline, fully mocked tests for the model client and pipeline, "
        "including the test that proves Member 1's parser plugs in cleanly.",
    ),
    # -- Logs -----------------------------------------------------------
    CuratedSource(
        "docs/evaluation/week2-ten-case-evaluation.md",
        DocumentType.LOG,
        "week2-ten-case-evaluation.md",
        "Member 4 (Week 2)",
        "The scored results of actually running the ten propose_action "
        "cases: a real record of a real evaluation run (8 PASS, 2 "
        "deliberate red-team FAIL), not a specification.",
    ),
    CuratedSource(
        "docs/evaluation/week3-fifteen-case-rag-evaluation.md",
        DocumentType.LOG,
        "week3-fifteen-case-rag-evaluation.md",
        "Member 4 (Week 3)",
        "The scored results of actually running fifteen retrieval cases "
        "against the live pipeline, including the four documented, "
        "reproduced retrieval-limitation cases.",
    ),
)

# The offline test-suite log is generated, not copied: it is produced by
# actually running the repository's real offline tests (see
# ``_collect_test_suite_log`` below), the same way Member 2's own fixture log
# (tests/fixtures/member2/corpus/logs/test_run_2026_09_15.log) was produced by
# actually running pytest against the fixture login service. It is added to
# the register alongside the curated sources above.
TEST_SUITE_LOG_MODULES: tuple[str, ...] = (
    "tests.test_config",
    "tests.test_prompt_harness",
    "tests.test_rag_eval",
    "tests.integration.test_model_integration",
    "tests.integration.test_rag_pipeline",
)


@dataclass(frozen=True)
class ProvenanceRecord:
    """One row of the Corpus/Source Register."""

    source_path: str  # path inside the materialized corpus (SourceDocument.source_path)
    original_path: str  # real path in the repository this was collected from
    doc_type: DocumentType
    requirement_id: str | None
    collected_by: str
    collected_at: str
    sha256: str
    byte_count: int
    line_count: int
    reason: str

    def to_source_document(self, text: str) -> SourceDocument:
        return SourceDocument(
            source_path=self.source_path,
            text=text,
            doc_type=self.doc_type,
            requirement_id=self.requirement_id,
        )


def _extract_docx_text(path: Path) -> str:
    if docx is None:
        raise RuntimeError(
            "python-docx is required to extract text from "
            f"{path.name}. Install it with: pip install python-docx"
        )
    document = docx.Document(str(path))
    parts: list[str] = []
    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            parts.append(paragraph.text)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _read_source_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return _extract_docx_text(path)
    return path.read_text(encoding="utf-8")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _collect_curated_documents(
    repo_root: Path, collected_at: str
) -> list[tuple[ProvenanceRecord, str]]:
    results: list[tuple[ProvenanceRecord, str]] = []
    missing: list[str] = []
    for source in CURATED_SOURCES:
        real_path = repo_root / source.original_path
        if not real_path.exists():
            missing.append(source.original_path)
            continue
        text = _read_source_text(real_path)
        record = ProvenanceRecord(
            source_path=f"{_TYPE_DIR_NAME[source.doc_type]}/{source.corpus_name}",
            original_path=source.original_path,
            doc_type=source.doc_type,
            requirement_id=source.requirement_id,
            collected_by=source.collected_by,
            collected_at=collected_at,
            sha256=_sha256(text),
            byte_count=len(text.encode("utf-8")),
            line_count=len(text.splitlines()),
            reason=source.reason,
        )
        results.append((record, text))

    if missing:
        joined = "\n  - ".join(missing)
        raise FileNotFoundError(
            "The following curated sources are listed in CURATED_SOURCES but "
            f"do not exist in this working tree:\n  - {joined}\n"
            "Update CURATED_SOURCES in tag_provenance.py if a file moved or "
            "was renamed."
        )
    return results


def _collect_test_suite_log(
    repo_root: Path, collected_at: str
) -> tuple[ProvenanceRecord, str] | None:
    """Actually run the offline test suite and capture its real output.

    Runs the exact command section 5 of ``docs/requirements/week2/setup.md``
    documents, as a real subprocess against the repository root -- not
    ``unittest discover`` (silently skips the integration tests, because
    ``tests/`` and ``tests/integration/`` are not importable packages yet)
    and not an in-process ``TestLoader`` (the ``tests`` package is only
    importable with the repository root on ``sys.path``, which this
    process does not add for itself).
    """

    import re
    import subprocess

    command = ["python3", "-m", "unittest", *TEST_SUITE_LOG_MODULES, "-v"]
    env = {**__import__("os").environ, "PYTHONPATH": "src"}
    completed = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = completed.stdout + completed.stderr

    summary_match = re.search(
        r"Ran (\d+) tests? in [\d.]+s\s*\n+(OK|FAILED)(?: \(([^)]*)\))?",
        output,
    )
    if summary_match:
        tests_run = int(summary_match.group(1))
        status_detail = summary_match.group(3) or ""
    else:
        tests_run = 0
        status_detail = "unable to parse summary"

    header = f"$ PYTHONPATH=src {' '.join(command)}\n# captured {collected_at}\n\n"
    footer = f"\n# exit code {completed.returncode}: {tests_run} tests run ({status_detail or 'all passed'})\n"
    text = header + output + footer

    if completed.returncode != 0:
        print(
            "  WARNING: the offline test suite did not pass while capturing "
            "this log -- captured the real failing output anyway rather "
            "than hiding it; investigate before relying on this as a clean "
            "baseline.",
            file=sys.stderr,
        )

    record = ProvenanceRecord(
        source_path=f"{_TYPE_DIR_NAME[DocumentType.LOG]}/offline-test-suite.log",
        original_path=(
            "generated by running "
            f"{', '.join(TEST_SUITE_LOG_MODULES)} (see setup.md section 5)"
        ),
        doc_type=DocumentType.LOG,
        requirement_id=None,
        collected_by="src/ingestion/tag_provenance.py",
        collected_at=collected_at,
        sha256=_sha256(text),
        byte_count=len(text.encode("utf-8")),
        line_count=len(text.splitlines()),
        reason=(
            "A real captured run of the team's actual offline test suite "
            f"({tests_run} tests), so the corpus has at least one genuine "
            "runtime log alongside the requirement and code documents, not "
            "only Member 2's synthetic fixture log."
        ),
    )
    return record, text


def _write_corpus(records_and_text: list[tuple[ProvenanceRecord, str]]) -> None:
    if CORPUS_DIR.exists():
        for existing in CORPUS_DIR.rglob("*"):
            if existing.is_file():
                existing.unlink()
    for record, text in records_and_text:
        destination = CORPUS_DIR / record.source_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")


def _write_json_register(records: list[ProvenanceRecord]) -> None:
    JSON_REGISTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_by": "src/ingestion/tag_provenance.py",
        "document_count": len(records),
        "documents": [
            {
                "source_path": record.source_path,
                "doc_type": record.doc_type.value,
                "requirement_id": record.requirement_id,
                "original_path": record.original_path,
                "collected_by": record.collected_by,
                "collected_at": record.collected_at,
                "sha256": record.sha256,
                "byte_count": record.byte_count,
                "line_count": record.line_count,
                "reason": record.reason,
            }
            for record in records
        ],
    }
    JSON_REGISTER_PATH.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _write_markdown_register(records: list[ProvenanceRecord]) -> None:
    counts: dict[DocumentType, int] = {}
    for record in records:
        counts[record.doc_type] = counts.get(record.doc_type, 0) + 1

    lines: list[str] = []
    lines.append("# Corpus / Source Register")
    lines.append("")
    lines.append("**Owner:** Member 1 — Project/Requirements Lead")
    lines.append(
        "**Produced by:** `src/ingestion/tag_provenance.py` "
        "(re-run it to regenerate this file and `knowledge/corpus/`)"
    )
    lines.append(f"**Generated:** {records[0].collected_at}")
    lines.append(f"**Documents:** {len(records)}")
    lines.append("")
    lines.append(
        "This is the register of every real document collected for the "
        "agent's retrieval corpus (`knowledge/corpus/`): where it lives in "
        "the materialized corpus, which real file in this repository it was "
        "collected from, who produced that original file, and a SHA-256 of "
        "the extracted text so any drift between this register and the "
        "corpus is detectable. It answers the Week 3 brief's requirement to "
        "tag each collected document with where it came from."
    )
    lines.append("")
    lines.append(
        "Machine-readable version: `knowledge/source-register.json` "
        "(directly loadable as the `SourceDocument` list "
        "`build_retrieval_pipeline` expects — see "
        "`load_documents_from_register()` in this script)."
    )
    lines.append("")
    lines.append("## Counts by type")
    lines.append("")
    lines.append("| Type | Count |")
    lines.append("| --- | --- |")
    for doc_type in DocumentType:
        if doc_type in counts:
            lines.append(f"| {doc_type.value} | {counts[doc_type]} |")
    lines.append("")
    lines.append("## Register")
    lines.append("")
    lines.append(
        "| Corpus path | Original source (provenance) | Type | Req. ID | "
        "Collected by | SHA-256 (first 12) | Why it's here |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for record in records:
        lines.append(
            f"| `{record.source_path}` | `{record.original_path}` | "
            f"{record.doc_type.value} | {record.requirement_id or '—'} | "
            f"{record.collected_by} | `{record.sha256[:12]}` | {record.reason} |"
        )
    lines.append("")

    MD_REGISTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    MD_REGISTER_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_documents_from_register(
    register_path: Path | str = JSON_REGISTER_PATH,
    corpus_dir: Path | str = CORPUS_DIR,
) -> list[SourceDocument]:
    """Load the real, tagged corpus as ``SourceDocument`` objects.

    This is the real replacement for ``load_documents_from_directory`` in
    ``src/rag/retrieval.py`` -- it reads the register this script wrote
    rather than re-guessing a file's type from its suffix.
    """

    register_path = Path(register_path)
    corpus_dir = Path(corpus_dir)
    payload = json.loads(register_path.read_text(encoding="utf-8"))

    documents: list[SourceDocument] = []
    for entry in payload["documents"]:
        text = (corpus_dir / entry["source_path"]).read_text(encoding="utf-8")
        documents.append(
            SourceDocument(
                source_path=entry["source_path"],
                text=text,
                doc_type=DocumentType(entry["doc_type"]),
                requirement_id=entry["requirement_id"],
            )
        )
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-test-log",
        action="store_true",
        help=(
            "Skip actually running the offline test suite to capture a log "
            "document (useful if the test dependencies are not installed)."
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "After writing the corpus, load it back through "
            "load_documents_from_register() and build_retrieval_pipeline() "
            "to confirm the register is actually usable, not just written."
        ),
    )
    args = parser.parse_args()

    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"Collecting corpus from {REPO_ROOT} ...")
    records_and_text = _collect_curated_documents(REPO_ROOT, collected_at)
    print(f"  {len(records_and_text)} curated document(s) read.")

    if not args.skip_test_log:
        log_entry = _collect_test_suite_log(REPO_ROOT, collected_at)
        if log_entry is not None:
            records_and_text.append(log_entry)
            print(
                f"  1 offline test-suite log captured "
                f"({log_entry[0].line_count} lines)."
            )

    records = [record for record, _ in records_and_text]
    _write_corpus(records_and_text)
    _write_json_register(records)
    _write_markdown_register(records)

    print(f"\nWrote {len(records)} documents to {CORPUS_DIR.relative_to(REPO_ROOT)}/")
    print(f"Wrote {JSON_REGISTER_PATH.relative_to(REPO_ROOT)}")
    print(f"Wrote {MD_REGISTER_PATH.relative_to(REPO_ROOT)}")

    if args.verify:
        print("\nVerifying: loading the register back through the real pipeline...")
        from rag.retrieval import build_retrieval_pipeline

        documents = load_documents_from_register()
        pipeline = build_retrieval_pipeline(documents, corpus_version=collected_at)
        print(
            f"  build_retrieval_pipeline() succeeded: "
            f"{pipeline.manifest.document_count} documents, "
            f"{pipeline.manifest.chunk_count} chunks, "
            f"fingerprint={pipeline.manifest.corpus_fingerprint}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
