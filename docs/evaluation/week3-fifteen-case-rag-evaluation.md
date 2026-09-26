# Week 3 RAG Evaluation — 15 cases

- Corpus: `tests/fixtures/member2/corpus` (Member 1's tag_provenance corpus is not landed yet; this is the same development fixture Member 2's integration tests use).
- Cases: 15 (8 answerable, 3 deliberately unanswerable, 4 partially answerable)
- PASS: 11  |  PARTIAL (documented known limitation): 4  |  FAIL (regression): 0

PARTIAL means the case reproduces a specific, documented retrieval limitation described in the Failure Catalogue below; it counts as an expected outcome, not a defect the harness missed. FAIL means the pipeline no longer matches even its documented behaviour for that case.

| Case | Category | Expected not-in-corpus | Actual | Required source(s) | Returned source(s) | Top-ranked source | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- |
| answerable_reject_incorrect_password | answerable | False | False | requirements/authentication.md | requirements/authentication.md | requirements/authentication.md | PASS |
| answerable_lockout_threshold | answerable | False | False | requirements/authentication.md | logs/test_run_2026_09_15.txt, requirements/authentication.md, src/login_service.py | requirements/authentication.md | PASS |
| answerable_no_credentials_in_logs | answerable | False | False | requirements/authentication.md | requirements/authentication.md | requirements/authentication.md | PASS |
| answerable_counter_reset | answerable | False | False | requirements/authentication.md | logs/test_run_2026_09_15.txt, requirements/authentication.md | requirements/authentication.md | PASS |
| answerable_service_unavailable_behavior | answerable | False | False | src/login_service.py | logs/test_run_2026_09_15.txt, requirements/authentication.md, src/login_service.py | src/login_service.py | PASS |
| answerable_max_failed_attempts_constant | answerable | False | False | src/login_service.py | logs/test_run_2026_09_15.txt, requirements/authentication.md, src/login_service.py | src/login_service.py | PASS |
| answerable_authentication_result_fields | answerable | False | False | src/login_service.py | requirements/authentication.md, src/login_service.py | src/login_service.py | PASS |
| answerable_cross_document_distinguish_failure_modes | answerable | False | False | requirements/authentication.md, src/login_service.py | logs/test_run_2026_09_15.txt, requirements/authentication.md, src/login_service.py | requirements/authentication.md | PASS |
| unanswerable_kubernetes_ingress | unanswerable | True | True | (none) | (none) | (none) | PASS |
| unanswerable_marketing_email_template | unanswerable | True | True | (none) | (none) | (none) | PASS |
| unanswerable_mfa_keyword_overlap_trap | unanswerable | True | True | (none) | (none) | (none) | PASS |
| partially_answerable_verbose_phrasing_false_negative | partially_answerable | True | True | (none) | (none) | (none) | PARTIAL |
| partially_answerable_ranking_inversion | partially_answerable | False | False | requirements/authentication.md | logs/test_run_2026_09_15.txt, requirements/authentication.md | logs/test_run_2026_09_15.txt | PARTIAL |
| partially_answerable_multi_document_dilution | partially_answerable | False | False | requirements/authentication.md | requirements/authentication.md | requirements/authentication.md | PARTIAL |
| partially_answerable_log_fragmentation | partially_answerable | False | False | logs/test_run_2026_09_15.txt | logs/test_run_2026_09_15.txt | logs/test_run_2026_09_15.txt | PARTIAL |

## Case questions

- **answerable_reject_incorrect_password** (answerable): 'What happens when a user enters an incorrect password?' — Matches REQ-AUTH-01 directly.
- **answerable_lockout_threshold** (answerable): 'How many consecutive failed login attempts lock an account?' — Matches REQ-AUTH-02 (five consecutive failures).
- **answerable_no_credentials_in_logs** (answerable): 'May a password appear in a log entry?' — Matches REQ-AUTH-03 (no credential material in logs).
- **answerable_counter_reset** (answerable): 'What resets the failed-attempt counter to zero?' — Matches REQ-AUTH-02 (a successful login resets the counter).
- **answerable_service_unavailable_behavior** (answerable): 'What does authenticate() return when service_available is False?' — Matches the service_unavailable branch in login_service.py.
- **answerable_max_failed_attempts_constant** (answerable): 'What is the value of MAX_FAILED_ATTEMPTS in the login service?' — Matches the module-level constant in login_service.py.
- **answerable_authentication_result_fields** (answerable): 'What fields does the AuthenticationResult dataclass contain?' — Matches the AuthenticationResult dataclass definition.
- **answerable_cross_document_distinguish_failure_modes** (answerable): 'How does the code distinguish invalid credentials from an unavailable authentication service?' — A genuine multi-source question that the pipeline grounds correctly, cited here as the contrast case for the partially-answerable multi-document questions below.
- **unanswerable_kubernetes_ingress** (unanswerable): 'How do we configure Kubernetes ingress certificates for the login service?' — The topic is entirely absent from the corpus.
- **unanswerable_marketing_email_template** (unanswerable): 'What is the password reset email template used by the marketing team?' — The topic is entirely absent from the corpus.
- **unanswerable_mfa_keyword_overlap_trap** (unanswerable): 'Does the system support multi-factor authentication?' — Deliberately shares the word 'authentication' with the corpus. Confirms the not-in-corpus decision is not fooled by a single overlapping keyword.
- **partially_answerable_verbose_phrasing_false_negative** (partially_answerable): 'Which test failed in the September 15 run, and what was the exact assertion error message?' — Documented retrieval failure #1: false not-in-corpus from verbose phrasing.
- **partially_answerable_ranking_inversion** (partially_answerable): 'What must the service do when it locks an account?' — Documented retrieval failure #2: correct source present but not ranked first.
- **partially_answerable_multi_document_dilution** (partially_answerable): 'Why did the account lockout test fail, and does the five-failure threshold in the test match the requirement and the code?' — Documented retrieval failure #3: confident-but-incomplete grounding on a cross-document question.
- **partially_answerable_log_fragmentation** (partially_answerable): 'Which test failed in the test run log?' — Documented retrieval failure #4: a single incident fragmented across chunks, only one of which is retrieved.

## Retrieval / Grounding Failure Catalogue

Four genuine failures, found by probing the live pipeline over the fixture corpus rather than invented, each with a distinct root cause:

### 1. partially_answerable_verbose_phrasing_false_negative

**Question:** 'Which test failed in the September 15 run, and what was the exact assertion error message?'

**Observed:** not_in_corpus=True, returned source(s)=(none)
**A fully correct grounding would cite:** ['logs/test_run_2026_09_15.txt']

**Root cause:** The test-run log genuinely names the failing test and its assertion message, so a fully correct system should answer this. But min_term_coverage is the fraction of ALL query terms a single chunk must contain, and this natural phrasing adds terms ('september', 'run', 'exact', 'message') that no single log chunk contains together. No chunk clears the 0.34 coverage floor, so the pipeline reports not_in_corpus=True. This is a false negative caused by query verbosity diluting the coverage ratio, not by a real gap in the corpus.

### 2. partially_answerable_ranking_inversion

**Question:** 'What must the service do when it locks an account?'

**Observed:** not_in_corpus=False, returned source(s)=['logs/test_run_2026_09_15.txt', 'requirements/authentication.md']
**A fully correct grounding would cite:** ['requirements/authentication.md']

**Root cause:** The authoritative requirement (REQ-AUTH-02: 'return a lockout reason') is retrieved but ranks 3rd of the 5 returned chunks, behind two test-log chunks that only share surface vocabulary ('account', 'locks', 'service') without stating the rule. BM25 scores literal term overlap, and the log's incidental phrasing happens to overlap the question's wording more than the requirement's own wording does. A consumer reading only the top-ranked chunk would miss the actual answer.

### 3. partially_answerable_multi_document_dilution

**Question:** 'Why did the account lockout test fail, and does the five-failure threshold in the test match the requirement and the code?'

**Observed:** not_in_corpus=False, returned source(s)=['requirements/authentication.md']
**A fully correct grounding would cite:** ['requirements/authentication.md', 'logs/test_run_2026_09_15.txt', 'src/login_service.py']

**Root cause:** This question genuinely spans three documents: the requirement, the failing test's log entry, and the code under test. The coverage floor is applied per chunk independently. Only the requirement chunk clears 0.34 coverage; the log chunk that explains the actual failure (0.30) and the code chunk (about 0.10) both fall just under the floor and are silently dropped. The pipeline reports full groundedness (not_in_corpus=False) while citing only one of the three relevant sources, so the answer looks complete but is not.

### 4. partially_answerable_log_fragmentation

**Question:** 'Which test failed in the test run log?'

**Observed:** not_in_corpus=False, returned source(s)=['logs/test_run_2026_09_15.txt']
**A fully correct grounding would cite:** ['logs/test_run_2026_09_15.txt#L4-L7', 'logs/test_run_2026_09_15.txt#L12-L17', 'logs/test_run_2026_09_15.txt#L19-L19']

**Root cause:** The single failure record in the log is split across multiple small chunks by paragraph-boundary chunking: the test list naming the failing test, the traceback header, and the assertion message each land in separate chunks. For this phrasing only the test-list chunk clears the coverage floor, so the pipeline correctly names the failing test but omits the assertion message and traceback that a complete answer needs, even though that text is a few lines away in the same file.
