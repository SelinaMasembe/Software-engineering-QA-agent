# Corpus / Source Register

**Owner:** Member 1 — Project/Requirements Lead
**Produced by:** `src/ingestion/tag_provenance.py` (re-run it to regenerate this file and `knowledge/corpus/`)
**Generated:** 2026-09-18T07:40:19Z
**Documents:** 22

This is the register of every real document collected for the agent's retrieval corpus (`knowledge/corpus/`): where it lives in the materialized corpus, which real file in this repository it was collected from, who produced that original file, and a SHA-256 of the extracted text so any drift between this register and the corpus is detectable. It answers the Week 3 brief's requirement to tag each collected document with where it came from.

Machine-readable version: `knowledge/source-register.json` (directly loadable as the `SourceDocument` list `build_retrieval_pipeline` expects — see `load_documents_from_register()` in this script).

## Counts by type

| Type | Count |
| --- | --- |
| requirement | 8 |
| code | 11 |
| log | 3 |

## Register

| Corpus path | Original source (provenance) | Type | Req. ID | Collected by | SHA-256 (first 12) | Why it's here |
| --- | --- | --- | --- | --- | --- | --- |
| `requirements/project-charter-and-user-stories.txt` | `docs/requirements/Project_charter and user stories.docx` | requirement | — | Member 1 (Week 1) | `78a32c1af7da` | The project charter and all twelve user stories with acceptance criteria -- the source of truth every other document traces back to. |
| `requirements/qa-agent-architecture-week1.txt` | `docs/architecture/QA_Agent_Architecture_Week1.docx` | requirement | — | Member 2 (Week 1) | `566af853b8cd` | The approved system architecture the retrieval pipeline and tool contracts are built against. |
| `requirements/ai-engineering-design-notes.txt` | `docs/architecture/Member3_AIEngineering_Deliverables.docx` | requirement | — | Member 3 (Week 1) | `39cf17cf3b3e` | The AI engineering design notes: prompting approach, model boundaries, and the risk register (R1-R9) later cases test against. |
| `requirements/prompt-specification.txt` | `docs/prompts/Prompt_Specification.docx` | requirement | — | Member 3 (Week 2) | `ec18dec4a315` | The full prompt specification behind propose_action, including the failure-behaviour contract the malformed-source-code case relies on. |
| `requirements/model-selection-note.txt` | `docs/prompts/Model_Selection_Note.docx` | requirement | — | Member 3 (Week 2) | `d90957a053d3` | The model selection rationale the ChatCompletionsClient is built against. |
| `requirements/propose-action-prompt-v1.0.md` | `docs/prompts/propose_action/v1.0.md` | requirement | — | Member 3 (Week 2) | `149bc8497f68` | First approved version of the propose_action prompt contract. |
| `requirements/propose-action-prompt-v1.1.md` | `docs/prompts/propose_action/v1.1.md` | requirement | — | Member 3 (Week 2) | `2777d7e03db4` | Current approved version of the propose_action prompt contract (adds the system-prompt confidentiality clause from US-11's Week 2 amendment). |
| `requirements/week2-test-case-traceability.md` | `docs/requirements/week2-test-case-traceability.md` | requirement | — | Member 1 (Week 2) | `5eac466b7436` | Maps all ten of Member 4's evaluation cases to the user stories they exercise, including the two acceptance-criteria resolutions. |
| `code/config_loader.py` | `src/config/loader.py` | code | — | Member 5 | `627d142765c3` | Loads and validates model configuration from the environment. |
| `code/models_client.py` | `src/models/client.py` | code | — | Member 2 (Week 2) | `e0abc97e6f8a` | The hand-rolled HTTP client that calls the model provider and translates provider failures into typed errors. |
| `code/models_types.py` | `src/models/types.py` | code | — | Member 1 (Week 2) | `045b877957d9` | The domain model: ProposalSet, TestProposal, and the traceable-citation check (validate_sources) that enforces US-8 in code. |
| `code/prompts_loader.py` | `src/prompts/loader.py` | code | — | Member 3 (Week 2) | `b8e7af7d8c43` | Loads a versioned prompt file by id and version. |
| `code/rag_chunking.py` | `src/rag/chunking.py` | code | — | Member 2 (Week 3) | `036ec67ac1ad` | Defines the SourceDocument/Chunk contract this script fills, and the boundary-aware splitter that turns a document into chunks. |
| `code/rag_retriever.py` | `src/rag/retriever.py` | code | — | Member 2 (Week 3) | `2bfe289868e8` | The deterministic BM25 lexical retriever the pipeline ranks chunks with. |
| `code/rag_retrieval.py` | `src/rag/retrieval.py` | code | — | Member 2 (Week 3) | `86269b8629f9` | The retrieval pipeline itself: indexes a corpus and makes the not_in_corpus decision in ordinary code, not the model. |
| `code/member1_types_smoke.py` | `scripts/member1_types_smoke.py` | code | — | Member 1 (Week 2) | `da1d824bb44c` | Runs the real ten evaluation cases through the domain model as a development smoke check. |
| `code/member2_model_smoke.py` | `scripts/member2_model_smoke.py` | code | — | Member 2 (Week 2) | `80932be85182` | Sends one real, sanitized request through the model client as a live smoke check. |
| `code/test_prompt_harness.py` | `tests/test_prompt_harness.py` | code | — | Member 4 (Week 2) | `ad65641542f6` | The offline harness that scores every propose_action case against its expected action, evidence, and confidence. |
| `code/test_model_integration.py` | `tests/integration/test_model_integration.py` | code | — | Member 2 (Week 2) | `dadb3b4de5c3` | Offline, fully mocked tests for the model client and pipeline, including the test that proves Member 1's parser plugs in cleanly. |
| `logs/week2-ten-case-evaluation.md` | `docs/evaluation/week2-ten-case-evaluation.md` | log | — | Member 4 (Week 2) | `86462d02ac18` | The scored results of actually running the ten propose_action cases: a real record of a real evaluation run (8 PASS, 2 deliberate red-team FAIL), not a specification. |
| `logs/week3-fifteen-case-rag-evaluation.md` | `docs/evaluation/week3-fifteen-case-rag-evaluation.md` | log | — | Member 4 (Week 3) | `cec70b725698` | The scored results of actually running fifteen retrieval cases against the live pipeline, including the four documented, reproduced retrieval-limitation cases. |
| `logs/offline-test-suite.log` | `generated by running tests.test_config, tests.test_prompt_harness, tests.test_rag_eval, tests.integration.test_model_integration, tests.integration.test_rag_pipeline (see setup.md section 5)` | log | — | src/ingestion/tag_provenance.py | `e41e06d21e01` | A real captured run of the team's actual offline test suite (46 tests), so the corpus has at least one genuine runtime log alongside the requirement and code documents, not only Member 2's synthetic fixture log. |

