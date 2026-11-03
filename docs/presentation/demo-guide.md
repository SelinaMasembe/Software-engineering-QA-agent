# Demo Guide: Running the QA Agent Live

How to run every part of the final presentation demo, in order, from a clean
terminal. Every command was run on Windows (Git Bash and PowerShell) on
3 Nov 2026. Offline steps need no API key and make no network calls.

## Before you start

Run these once, from the repository root.

1. **Use `python`, not `python3`.** On Windows, `python3` often opens the
   Microsoft Store prompt instead of running Python. Check with:

   ```bash
   python --version
   ```

   Any Python 3.12 or newer works.

2. **Install the dependencies** (only if you have not already):

   ```bash
   python -m pip install -r requirements.txt
   ```

3. **Tell Python where the code lives.** Every command below needs the `src`
   folder on the path.

   | Shell | How |
   | --- | --- |
   | Git Bash | Put `PYTHONPATH=src` in front of each command, as shown below |
   | PowerShell | Run `$env:PYTHONPATH = "src"` once per window, then drop the `PYTHONPATH=src` prefix |

   The Git Bash form `PYTHONPATH=src python ...` does not work in PowerShell.

4. **Quote the whole goal.** If the terminal shows a `>` prompt and waits, a
   closing `"` is missing. Press Ctrl+C and type the line again.

## The demo, in order

### 1. One agent session (offline)

The real sensor, planner, citation check and agent loop, with an offline stub
standing in for the model.

```bash
PYTHONPATH=src python scripts/run_agent_session.py --goal "Propose a test that the account locks after five failed login attempts."
```

What you should see:

- `PLAN` with `live: off (offline stub, no network)` and `prompt: v1.3`.
- `RESULT` with `status: completed`, `iterations: 1`,
  `final_action: propose_test`, and the cited paths
  `requirements/authentication.md` and `src/login_service.py`.
- `PROPOSAL` with the full proposal: action, arguments, rationale, each
  citation with its note, and confidence.

What it shows: BM25 retrieval found the lockout requirement and the login
code, the evidence was wrapped and guarded by `build_context`, and the
proposal passed `validate_citations` because it cites only what it was shown.
The stub's reply is canned, so it says nothing about how a model behaves.

### 2. Human approval (offline)

`run_tests` waits for a named human, runs once, and cannot be replayed.

```bash
PYTHONPATH=src python scripts/member5_approval_demo.py
```

What you should see:

1. The first request is queued (`awaiting_approval`) and nothing runs.
2. `Alice approved request ...`, then the same request runs once in the
   sandbox, and the allow-listed test passes.
3. The same request again is queued again: the approval was consumed.
4. The audit log: `approval_requested`, `decision_recorded`,
   `approval_consumed`.

The demo writes only to a temporary folder.

### 3. A saved run as a timeline (offline)

```bash
PYTHONPATH=src python scripts/show_run_log.py --last
```

This prints the newest run saved in `evidence/traces/runs/`. Today that is
the Week 5 approval run (a scripted planner). Point out:

- line 9, `human approval_granted ... approver=Alice`;
- line 14, `loop_halted reason=iteration_cap` after 3 iterations (that demo
  sets its own cap of 3; the shipped contract uses 5).

The `ai` label on `action_planned` lines comes from the loop, which labels
every planning step that way, even when the planner is scripted.

If anyone has run `run_agent_session.py --trace-dir evidence/traces/runs`,
`--last` shows that run instead, which has no approval step.

### 4. One agent session with the real model (live, optional)

Only if the network is reliable. Keep the recorded run (see "Fallback
evidence" below) ready in case the call fails.

First load your settings into this terminal. You need a `.env` file made
from `.env.example` with your own key in it. Never commit `.env`.

Git Bash:

```bash
set -a; . ./.env; set +a
PYTHONPATH=src python scripts/run_agent_session.py --goal "Propose a test that the account locks after five failed login attempts." --live --out evidence/test-runs/week8/agent-session/demo_live.json
```

PowerShell:

```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object { $n, $v = $_ -split '=', 2; Set-Item -Path "env:$($n.Trim())" -Value $v.Trim() }
python scripts/run_agent_session.py --goal "Propose a test that the account locks after five failed login attempts." --live --out evidence/test-runs/week8/agent-session/demo_live.json
```

What you should see: `live: ON (real model calls)` and
`model: gemini-2.5-flash`. On 3 Nov 2026 the run completed in 2 iterations:
Gemini used a tool first, then proposed the test, citing
`requirements/authentication.md` and `src/login_service.py`. The `PROPOSAL`
block shows the test Gemini wrote; check its steps against
`tests/fixtures/member2/corpus/src/login_service.py` before claiming it is
correct, because a valid citation does not prove the test is right.

`flag entries traced: 1` on that run came from the planner's history guard: it
redacted a credential-shaped pattern in the first tool output before Gemini
saw it. That flag was a false positive on ordinary code.

The run makes up to 5 model calls. It has no approval gate configured, so it
can never run tests or draft issues. The summary file holds no key and no
request headers.

### 5. Prove it works (offline)

```bash
python -m pytest -q
```

Expect about 739 passed, 1 skipped (a Windows-only file-permission test) and
637 subtests, in under two minutes.

```bash
python tests/run_scenarios.py --no-write
```

Expect `Scenarios: 61  PASS 54  PARTIAL 5  FAIL 2` and
`Result: all scenarios behaved as expected`. The 2 FAILs are red-team probes
that are expected to fail, and the 5 PARTIALs are documented known gaps.
Always pass `--no-write`, or the runner rewrites the committed results in
`evidence/evaluation/`.

```bash
python tests/test_failure_retest.py
```

Expect `F01` to `F06: PASS`. In PowerShell, run
`$env:PYTHONIOENCODING = "utf-8"` first so the output prints cleanly.

```bash
python scripts/check_sensitive.py --all
```

No output and exit code 0 means no secrets are committed.

## If something goes wrong

| What you see | Cause | What to do |
| --- | --- | --- |
| `Python was not found; run without arguments to install from the Microsoft Store` | You typed `python3` | Use `python` |
| `ModuleNotFoundError: No module named 'models'` (or `agent`, `rag`) | `src` is not on the path | Git Bash: add `PYTHONPATH=src`. PowerShell: `$env:PYTHONPATH = "src"` |
| A `>` prompt that waits | An unclosed quote | Ctrl+C, then retype the line |
| `Could not start: Required environment variable MODEL_ENDPOINT is missing.` | `.env` not loaded in this terminal | Run the load command from step 4 again |
| `planner_failure: client_error` | Gemini overloaded or a network blip | Wait a minute and retry |
| `planner_failure: rate_limited` | Free-tier quota used up | Wait, or show the fallback evidence |
| `planner_failure: authentication` | Wrong or expired key | Fix `MODEL_API_KEY` in `.env` |
| `status: no_action` with no cited paths | A vague goal found no evidence | Use the exact lockout goal above |

## Fallback evidence

If the live step fails, show these committed records instead.

| What | File |
| --- | --- |
| A live agent session (20 Oct 2026): completed in 2 iterations | `evidence/test-runs/week8/agent-session/live_session.json` |
| The model following an injected source comment (flagged as AI-1) | `evidence/test-runs/week8/real-model/20261016T145654Z_live/calls/adversarial_prompt_injection_in_source_comment__v1.3__run1.json` |
| The real-model trial run summary (6 PASS, 4 FAIL) | `evidence/test-runs/week8/real-model/20261016T145654Z_live/summary.json` |
| A failure-recovery trace (fabricated citation, then a shell command as a test ID) | `evidence/traces/runs/20261002T165513167983Z_week5-demo-failure-recovery_82f5e9a9.jsonl` |
| All 61 scenario results | `evidence/evaluation/week7-scenario-results.md` |

## After the demo

- `git status` should show no changes except, if you ran step 4, the new
  `evidence/test-runs/week8/agent-session/demo_live.json`. Commit it only if
  you want that run on record.
- Close the terminal used for the live run, so the key does not stay in its
  environment.
