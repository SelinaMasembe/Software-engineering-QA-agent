## Week 3 — Corpus collection; Grounding Design Note; src/rag/context_builder.py

**Date:** 19th Sept 2026
**Deliverable:** Initial `knowledge/corpus/` contents and source register, Grounding Design Note, `src/rag/context_builder.py`

**What I asked the AI for:** Help assembling an initial corpus from the team's own existing documents, a design note explaining how retrieved evidence becomes model context (token budget, source attribution, handling of no-results), and the code implementing it.

**What the AI produced:** The corpus was assembled from real files already produced earlier in this same set of conversations (the charter, boundary matrix, risk register, acceptance criteria review, architecture doc, design notes, prompt specs, and `loader.py`), not invented placeholder content. The Grounding Design Note and `context_builder.py` were both fully drafted, and the code was run against fabricated test chunks (not real retrieval output, since `src/rag/pipeline.py` didn't exist in the form assumed) to confirm the normal case, the not-in-corpus case, and the over-budget case all behaved correctly.

**Verification I performed myself:** I read through the Grounding Design Note and confirmed that it accurately described the intended behavior of the context-building process, including how it handles token budgets and source attribution. I also reviewed the `context_builder.py` code, ran the provided test cases, and verified that the outputs matched the expected results for each scenario. Additionally, I cross-referenced the code with the existing retrieval pipeline to ensure that it would integrate correctly once `src/rag/pipeline.py` was implemented. I cross-checked that the generated code would sync with the existing retrieval pipeline once `src/rag/pipeline.py` was implemented, and that the test cases covered the expected edge cases.

**What I changed or would still change myself:** `context_builder.py` was written against an *assumed* interface for the real retrieval pipeline, later confirmed inaccurate. **Update (26th Sept 2026): resolved.** The version actually committed to `src/rag/context_builder.py` imports `RetrievalResult` from `.retrieval` and reads `retrieved.chunk.text` / `retrieved.chunk.doc_type.value` / `retrieved.chunk.source_path` — the real `RetrievalPipeline.retrieve()` shape, not the originally-assumed free function. Confirmed directly by re-reading both files together and by `tests/integration/test_context_builder.py` passing (7/7) against the real pipeline. The interface concern only ever applied to an early hand-drafted, never-committed version of this file; nothing shipped against the wrong assumption.

One related item is still open, though: the Grounding Design Note **document itself** (`docs/context/Grounding_Design_Note.docx`) still has an "Interface Assumed From src/rag/pipeline.py" section describing the old, wrong assumption (`retrieve(query, top_k)` as a free function in `pipeline.py`) — confirmed by reading its actual text. That section needs rewriting to point at `src/rag/retrieval.py`'s `RetrievalPipeline.retrieve()` method before the note is submitted as final. Separately, its claim that "`doc_type` values come directly from the tags Member 1's `tag_provenance.py` produces" is now actually true (`src/ingestion/tag_provenance.py` exists and is the real source), so that part no longer needs a caveat.

**Not AI-generated:** The 11 real source files making up the initial corpus were produced across earlier team and AI-assisted work; only the *organization* and the tagging approach were new this week.

**Data sent to the AI:** The team's own existing documents (charter, architecture doc, risk register, etc.) and code files, all already team-owned material, no personal or production data.

**Evidence status:** Re-run today (26th Sept 2026):

```
$ PYTHONPATH=src python -m pytest tests/integration/test_context_builder.py -v
...
7 passed in 0.04s
```

Still to do: rewrite the stale "Interface Assumed" section in the Grounding Design Note docx (see above), and capture a screenshot of the passing test run as saved evidence.

---