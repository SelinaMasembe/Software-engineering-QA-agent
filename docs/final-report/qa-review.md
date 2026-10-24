# Final QA Review: Release Readiness

BSE4104 Software-Engineering QA Agent | Group J | Conducted by Member 5
(DevOps/Documentation Lead), 23 October 2026, on branch
`week8-member5-final-evidence` (based on `main` at `138c521`).

## 1. Verdict

**Ready to release, with three actions for owners before submission**
(section 4, items marked **Release blocker**).

- **Behaviour.** The system behaves as specified. All automated evidence is
  green:
  - 739 tests pass;
  - 61 of 61 evaluation scenarios behave as their owners expect;
  - the secret scan is clean.
- **Packaging.** The remaining gaps are in release packaging, not behaviour:
  - the release tag is missing;
  - final-report sections 4–7 are missing;
  - section 8 has small corrections.

## 2. Method

Each finding below was confirmed by running a command or reading the code.
None is speculation.

1. **Ran every automated check:** the full test suite, the scenario runner,
   the secret scan, every offline demo and smoke script, and `--help` on
   every command-line script.
2. **Reviewed the infrastructure code** (configuration, observability,
   scripts, Git hooks, dependencies) for defects, unsafe defaults and
   leaked secrets.
3. **Checked the instructions:** every README and setup command and path
   was checked against the repository.
4. **Mapped every brief deliverable to its evidence** (the mapping now
   lives in [`clickup-checklist.md`](clickup-checklist.md) and the report's
   appendices).
5. **Checked side effects:** whether any test writes into the real
   repository.

Severity scale:
- **High:** blocks the release or misleads a user.
- **Medium:** wrong behaviour or a security weakness.
- **Low:** an edge case or polish.

## 3. Findings fixed in this review (Member 5 scope)

Each fix has a regression test in `tests/test_config.py`,
`tests/test_check_sensitive.py` or `tests/test_week8_infra_fixes.py`.

| # | Severity | Finding | Fix |
| --- | --- | --- | --- |
| 1 | Medium | `ModelSettings` printed the API key in its text form (`src/config/loader.py`) | Key excluded from the printed form |
| 2 | Medium | `MODEL_TIMEOUT_SECONDS=nan` or `inf` passed validation and later crashed the HTTP client outside the error handlers; absurd token limits were accepted | Finite, bounded values only (timeout ≤ 600 s, tokens ≤ 65,536) |
| 3 | Medium | The README promised every run is saved, but live agent sessions kept their trace in memory only | `scripts/run_agent_session.py --trace-dir` saves the full run log through the run logger; README reworded |
| 4 | Medium | Approval queue and audit paths were relative to the current folder, so running from a subfolder created a separate, empty queue | Default is always the repository's `data/` folder (`approval_gate.py`, `approve_cli.py`) |
| 5 | Low | The secret scanner exited 0 ("clean") for a file it could not find, and resolved relative paths against the repo root instead of the current folder | Missing file gives exit code 2; paths resolve from the current folder |
| 6 | Low | `show_run_log.py` created the run-log folder while only reading, and could not open a file name it had just listed | Reads without writing; accepts listed names |
| 7 | Low | Run-log file names were labelled UTC (`…Z`) without converting from local time | Converted to UTC |
| 8 | Low | `load_index()` ignored `QA_AGENT_TRACE_DIR`; run-log counters advanced before a write succeeded | Follows the setting; counters advance only after the write |
| 9 | Low | An endpoint URL with spaces or embedded credentials was accepted; a blank optional setting errored instead of using its default | Rejected; blanks use defaults |
| 10 | Low | `.env.example` named a model (`gemini-3.5-flash-lite`) different from the one every live run used, and omitted `QA_AGENT_APPROVERS` | Now `gemini-2.5-flash`, with every setting documented |
| 11 | Hygiene | Unpinned dependencies; no CI; tracked `.DS_Store` files; a stale local `src/orchestration/` folder; scenario-runner owner label out of date | Versions pinned; GitHub Actions CI added (tests, scenarios, scan); junk untracked or removed; label corrected |

## 4. Open findings for other owners

| # | Severity | Owner | Finding | Recommended action |
| --- | --- | --- | --- | --- |
| A | **High: release blocker** | M2 | No release tag exists on GitHub (`git ls-remote --tags origin` is empty), yet the README tells users to `git checkout v1.0.0` | After the final merge: `git tag -a v1.0.0 -m "Final release" && git push origin v1.0.0` |
| B | **High: release blocker** | M3 / team | Final-report sections 4, 6 and 7 (M3) and section 5 (no owner in the plan) are not in the repository | Write and commit them; agree an owner for §5 |
| C | **Medium: release blocker** | M4 | Section 8 needs corrections: "two live calls" should be two runs with 25 calls; `telemetry.py` is credited to M5 but is M2's; a broken link to `week7-scenario-results.md` (the file is in `evidence/evaluation/`); stale commit reference `92fe86f` | Correct the text and link |
| D | Medium | M4 | `tests/test_stop_conditions.py` rewrites the committed traces `evidence/traces/week5-run-*.json` on every test run | Write to a temporary folder in the test; keep regeneration as a deliberate command |
| E | Medium | M3 | Prompt v1.3 tells the model it receives the tool schemas and the remaining iteration count; the planner sends neither. `Prompt_Specification.docx` covers v1.0–v1.1 only | Align the planner or the prompt; update the specification |
| F | Low | M1 | `TestProposal` and `TestOutcome` in `src/models/types.py` produce 6 pytest collection warnings | Add `__test__ = False` to both classes |
| G | Low | M1 | `Claude outputs/` (7 `.docx` files and a broken `verify_types.py`) is tracked but referenced nowhere | Move the reports into `docs/weekly reports/` and delete the broken script |
| H | Low | M2 | `member2_observability_demo.py` ignores `QA_AGENT_OBSERVABILITY_DIR` by default, and its self-checks use `assert`, which `python -O` removes | Resolve the setting at run time; raise explicit errors |
| I | Low | All | `python -m unittest discover -s tests` misses 237 tests (the integration folder has no `__init__.py`, and two files are pytest-style) | Always use `python -m pytest -q`, as the README and CI do |
| J | Low | M2 | No standalone Tool Catalogue document | Appendix D of the appendices now serves as one |

## 5. Evidence

```bash
python3 -m pytest -q                         # 739 passed
python3 tests/run_scenarios.py --no-write    # 61 scenarios, all as expected
python3 scripts/check_sensitive.py --all     # exit 0
```

Fixed-finding tests:
- `tests/test_config.py` (`Week8HardeningTests`)
- `tests/test_check_sensitive.py` (last two tests)
- `tests/test_week8_infra_fixes.py`

The CI workflow `.github/workflows/ci.yml` runs the same three commands on
every push once this branch is merged.
