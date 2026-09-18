#!/usr/bin/env python3
"""Prove the Week 3 corpus actually works, not just that it was written.

Loads the register src/ingestion/tag_provenance.py produced
(knowledge/source-register.json + knowledge/corpus/), builds it into a real
retrieval pipeline through src/rag/retrieval.py, and runs it against a
handful of real questions about this project -- including one question with
no answer in the corpus, to prove the pipeline says "not in corpus" instead
of making something up.

This is a development smoke runner, the same pattern as
scripts/member1_types_smoke.py and scripts/member2_model_smoke.py: it is not
part of the automated test suite, it is something you run yourself to see
the real thing work.

Usage (from the repository root):
    PYTHONPATH=src python3 scripts/member1_corpus_smoke.py
On Windows PowerShell:
    $env:PYTHONPATH = "src"
    python scripts\\member1_corpus_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ingestion.tag_provenance import (  # noqa: E402
    JSON_REGISTER_PATH,
    load_documents_from_register,
)
from rag.retrieval import build_retrieval_pipeline  # noqa: E402

# One deliberately unanswerable question is included: a working pipeline
# must say "not in corpus" for it, not guess. That is the whole point of the
# grounding guarantee this corpus exists to support.
DEMO_QUERIES: tuple[tuple[str, bool], ...] = (
    ("What does US-8 require about a proposal that cannot be traced to a source?", False),
    ("What must propose_action return if it cannot determine a grounded next action?", False),
    ("How many of the ten Week 2 evaluation cases passed?", False),
    ("What does validate_sources raise when a citation was never supplied?", False),
    ("What is the recommended seasoning method for a cast iron skillet?", True),
)


def main() -> int:
    if not JSON_REGISTER_PATH.exists():
        print(
            f"Could not find {JSON_REGISTER_PATH}.\n"
            "Run this first: PYTHONPATH=src python3 src/ingestion/tag_provenance.py",
            file=sys.stderr,
        )
        return 2

    print(f"Loading corpus from {JSON_REGISTER_PATH.relative_to(REPO_ROOT)} ...")
    documents = load_documents_from_register()
    pipeline = build_retrieval_pipeline(documents, corpus_version="smoke-run")
    print(
        f"Indexed {pipeline.manifest.document_count} documents into "
        f"{pipeline.manifest.chunk_count} chunks "
        f"(fingerprint={pipeline.manifest.corpus_fingerprint}).\n"
    )

    mismatches = 0
    for query, expect_not_in_corpus in DEMO_QUERIES:
        result = pipeline.retrieve(query)
        status = "NOT IN CORPUS" if result.not_in_corpus else "ANSWERED"
        print(f"Q: {query}")
        print(f"   -> {status}")
        if result.chunks:
            top = result.chunks[0]
            print(f"   top source: {top.chunk.source_path} (score={top.score})")
            print(f"   excerpt: {top.chunk.text[:160].strip()!r}")
        print()

        if result.not_in_corpus != expect_not_in_corpus:
            mismatches += 1
            print(
                f"   ** unexpected: expected "
                f"{'not-in-corpus' if expect_not_in_corpus else 'an answer'} **\n"
            )

    if mismatches:
        print(f"{mismatches} of {len(DEMO_QUERIES)} demo queries behaved unexpectedly.")
        return 1

    print(f"All {len(DEMO_QUERIES)} demo queries behaved as expected.")
    print(
        "This confirms the register and corpus files load, chunk, index, "
        "and retrieve correctly through the real Week 3 pipeline."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
