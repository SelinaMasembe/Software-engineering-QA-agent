# Week 5 Member 5: Run Log Saved to the Evidence Folder

## Ownership

Member 5 provides the trace sink that saves a log of every agent-loop run to
`evidence/traces/runs/`. Member 2's `AgentLoop` emits the trace entries; it
deliberately does not format or store them (see the `TraceSink` protocol in
`src/agent/loop.py`). `RunLogger` is that sink.

## What Gets Saved

For every run the loop starts, `RunLogger` writes:

| File                                                   | Contents                                                                                       |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| `evidence/traces/runs/<UTC start>_<session>_<id>.jsonl` | One JSON line per `TraceEntry`, in order: sense, plan, citation check, tool dispatch, stop     |
| `evidence/traces/runs/index.jsonl`                     | One summary row each time a run stops: outcome, start/end time, entry/tool/AI-decision counts |

Every line carries `schema`, `run_id` and `seq`, plus the `TraceEntry`
fields: `session_id`, `timestamp`, `actor` (`ai` or `deterministic`),
`action`, `detail`, and `tool_invocation` when a tool was dispatched.

Example line (from the failure/recovery demo run):

```json
{"schema": "qa-agent.run-log/v1", "run_id": "42dc361f37804a0d8ed9d7f6d054228c", "seq": 7, "session_id": "week5-demo-failure-recovery", "timestamp": "2026-10-01T15:47:26.540338+00:00", "actor": "deterministic", "action": "tool_dispatched", "detail": "iteration=2; kind=tool_rejected; code=invalid_arguments", "tool_invocation": {"tool_name": "run_tests", "input": {"argument_keys": ["session_id", "test_node_ids"]}, "output": {"kind": "tool_rejected", "code": "invalid_arguments", "output_keys": null, "output_bytes": null}, "called_at": "2026-10-01T15:47:26.540336+00:00"}}
```

## Run Boundaries

- `loop_started` always opens a new file, even when a session ID is reused.
- `loop_paused` (waiting for human approval) keeps the file open. The
  matching `loop_resumed` continues in the same file, so one approval
  hand-off reads as one run.
- `loop_completed`, `loop_halted` and `loop_failed` close the run.
- Every stop, including a pause, appends an index row. A resumed run
  therefore has two rows; `load_index()` returns only the latest one per run.
- An entry that arrives for a session with no open run is still saved in a
  new file, never dropped.

## Safety Guarantees

- **Fails closed.** Each line is flushed and `fsync`ed before `record`
  returns. A write failure is raised, not swallowed, so the loop stops with
  `LoopFailure.TRACE_FAILED` before any further action (US-10: no action
  without an audit trail). This is covered by a test.
- **Metadata only.** The loop already logs argument key names, statuses and
  output sizes, never argument values, file content or test output. The
  logger keeps that contract and adds nothing from the task or model output.
- **Redaction.** As a second line of defence, any string matching the
  credential patterns that `scripts/check_sensitive.py` blocks (Google API
  keys, `sk-` keys, GitHub/AWS/Slack tokens, JWTs, bearer tokens, private key
  blocks) is replaced with `[REDACTED]`. The line gets `"redacted": true` and
  the index counts redactions.
- **No path escape.** Session IDs are sanitized before they become file
  names, so a session ID such as `../../etc/passwd` cannot write outside the
  evidence folder.
- **Committable.** Files use `.jsonl`, not `.log`, because
  `check_sensitive.py` blocks `*.log`. Review run files before committing
  them as evidence.

## Configuration

| Setting              | Default                 | Purpose                                         |
| -------------------- | ----------------------- | ----------------------------------------------- |
| `QA_AGENT_TRACE_DIR` | `evidence/traces/runs/` | Redirect run logs, e.g. to a temporary folder for experiments |

`RunLogger(directory)` overrides both. Tests always use a temporary folder,
so running the suite never writes into `evidence/`.

## Wiring It Into the Loop

```python
from agent import AgentLoop
from observability import RunLogger

loop = AgentLoop(
    sensor=sensor,
    planner=planner,
    dispatcher=dispatcher,
    stop_evaluator=stop_evaluator,
    trace_sink=RunLogger(),  # saves every run to evidence/traces/runs/
)
```

## The Three Week 5 Execution Traces

`scripts/member5_run_log_demo.py` runs the real `AgentLoop`, citation
validator, `ToolDispatcher`, Member 3's `ReadFileTool` and `RunTestsTool`
(through the `SandboxExecutor`) and Member 5's `JSONApprovalGate`, and saves
three runs:

| Scenario             | What happens                                                                                                   | Outcome          |
| -------------------- | -------------------------------------------------------------------------------------------------------------- | ---------------- |
| `grounded-proposal`  | `read_file` on a registered corpus file, then a grounded `propose_test`                                         | `loop_completed` |
| `failure-recovery`   | A fabricated citation is rejected before dispatch; a `run_tests` request with an unknown node ID is refused; the agent recovers with a grounded proposal | `loop_completed` |
| `approval-pause-resume` | `run_tests` pauses the loop, "Alice" approves, the loop resumes, the deliberately failing sandbox test runs, then the iteration cap halts the loop. The trace includes Alice's `approval_granted` entry (`actor=human`) | `loop_halted`    |

The planner, sensor and stop evaluator in the demo are scripted stand-ins,
so the traces are reproducible offline without an API key. They are not the
model planner or Member 1's stop policy (`src/agent/stop_conditions.py`).

Member 4 separately captured the group's three Week 5 traces as JSON in
`evidence/traces/week5-run-*.json`. The run logger is what saves a log of
every run going forward, including human approval decisions when the gate is
given `trace_sink=RunLogger(...)`.

## Evidence Files

Primary implementation:

- `src/observability/run_logger.py`
- `src/observability/__init__.py`
- `scripts/member5_run_log_demo.py`
- `scripts/show_run_log.py`
- `tests/test_run_logger.py`
- `tests/integration/test_run_logger_agent_loop.py`

## Automated Verification

Run the run-logger unit tests (no agent loop needed):

```bash
PYTHONPATH=src python3 -m unittest tests.test_run_logger -v
```

Run the end-to-end tests with Member 2's loop and the real approval gate:

```bash
PYTHONPATH=src python3 -m unittest \
    tests.integration.test_run_logger_agent_loop -v
```

Produce the three demo traces in `evidence/traces/runs/`:

```bash
PYTHONPATH=src python3 scripts/member5_run_log_demo.py
```

List the saved runs, or print the newest one as a timeline:

```bash
PYTHONPATH=src python3 scripts/show_run_log.py
PYTHONPATH=src python3 scripts/show_run_log.py --last
```

Check the run files before committing them:

```bash
python3 scripts/check_sensitive.py evidence/traces/runs/*.jsonl
```

## Known Limits

- Human approval and denial decisions reach the run log only when the gate
  is constructed with `trace_sink`. The full decision record, including the
  human's reason text, stays in the gate's audit log (`data/audit.log`).
- Model name, prompt version, token usage and latency are not in
  `TraceEntry` yet, so they are not logged. Week 7 asks for them; they can be
  added to the trace detail without changing the file format.
