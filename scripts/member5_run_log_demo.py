#!/usr/bin/env python3
"""Produce three saved execution traces with Member 5's run logger.

Each scenario runs Member 2's real ``AgentLoop`` with the real citation
validator, ``ToolDispatcher``, Member 3's ``ReadFileTool`` and ``RunTestsTool``
(through the ``SandboxExecutor``) and Member 5's ``JSONApprovalGate``, and
saves the run through ``RunLogger``:

1. grounded-proposal      - read_file, then a grounded propose_test (completed).
2. failure-recovery       - a fabricated citation is rejected and an invalid
                            run_tests request is refused, then the agent
                            recovers with a grounded proposal (completed).
3. approval-pause-resume  - run_tests pauses the loop for human approval,
                            "Alice" approves, the loop resumes and the test
                            runs in the sandbox (it fails, as the fixture
                            intends), then the iteration cap halts the loop.
                            The human decision is recorded in the same trace.

The planner, sensor and stop evaluator are scripted stand-ins so the traces
are reproducible offline without an API key; they are not the model planner
or Member 1's stop policy. Approval queue and audit files go to a temporary
directory that is deleted afterwards.

Run from the repository root:
    PYTHONPATH=src python3 scripts/member5_run_log_demo.py
    PYTHONPATH=src python3 scripts/member5_run_log_demo.py --output-dir /tmp/runs
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent import AgentLoop, AgentTask, LoopStatus  # noqa: E402
from models.types import (  # noqa: E402
    Action,
    Confidence,
    EvidenceRef,
    ProposalSet,
    StopReason,
)
from observability import RunLogger, format_run, load_index, load_run  # noqa: E402
from orchestrator import ExecutionContext, ToolDispatcher, ToolRegistry  # noqa: E402
from orchestrator.approval_gate import (  # noqa: E402
    AuditLogger,
    JSONApprovalGate,
    JSONApprovalStore,
)
from rag import AssembledContext  # noqa: E402
from sandbox import SandboxExecutor  # noqa: E402
from tools import ReadFileTool, RunTestsTool  # noqa: E402

SOURCE = "code/config_loader.py"
REQUIREMENT = "requirements/project-charter-and-user-stories.txt"
FABRICATED = "pricing/discount_table.md"
FAILING_TEST = "tests/fixtures/sandbox/sample_cases.py::test_subtraction_deliberately_fails"


def proposal(action: Action, arguments: dict, evidence=(SOURCE,)) -> ProposalSet:
    return ProposalSet(
        action=action,
        arguments=arguments,
        rationale="Scripted Member 5 run-log demonstration step.",
        evidence=tuple(EvidenceRef(source_path=path) for path in evidence),
        confidence=Confidence.HIGH,
    )


def propose_test() -> ProposalSet:
    return proposal(
        Action.PROPOSE_TEST,
        {"title": "Missing MODEL_API_KEY raises a configuration error"},
        evidence=(SOURCE, REQUIREMENT),
    )


def run_failing_test(session_id: str) -> ProposalSet:
    return proposal(
        Action.RUN_TESTS,
        {"test_node_ids": [FAILING_TEST], "session_id": session_id},
    )


class ScriptedSensor:
    """Stand-in for retrieval plus rag.build_context."""

    def sense(self, task, state):
        return AssembledContext(
            text="<evidence>scripted demo context</evidence>",
            chunks_used=2,
            chunks_dropped=0,
            not_in_corpus=False,
            allowed_source_paths=frozenset({SOURCE, REQUIREMENT}),
        )


class ScriptedPlanner:
    """Stand-in for the propose_action model call."""

    def __init__(self, *proposals: ProposalSet) -> None:
        self.proposals = list(proposals)

    def plan(self, task, context, state):
        return self.proposals.pop(0)


class IterationCap:
    """Stand-in for Member 1's stop evaluator: iteration cap only."""

    def __init__(self, cap: int) -> None:
        self.cap = cap

    def evaluate(self, state):
        if state.iterations_completed >= self.cap:
            return StopReason.ITERATION_CAP
        return None


def run_scenario(name, logger, gate, planner, cap) -> None:
    dispatcher = ToolDispatcher(
        ToolRegistry(
            [
                ReadFileTool(),
                RunTestsTool({FAILING_TEST}, SandboxExecutor()),
            ]
        ),
        approval_gate=gate,
    )
    loop = AgentLoop(
        sensor=ScriptedSensor(),
        planner=planner,
        dispatcher=dispatcher,
        stop_evaluator=IterationCap(cap),
        trace_sink=logger,
    )
    context = ExecutionContext(
        session_id=f"week5-demo-{name}", actor_id="qa-agent", role="developer"
    )
    result = loop.run(
        AgentTask(goal="Propose a test for configuration loading.", context=context)
    )

    while result.status is LoopStatus.AWAITING_APPROVAL:
        # Play the human at the approval CLI, then let the agent continue.
        request = gate.store.list_pending()[0]
        gate.decide(
            request.id,
            approve=True,
            decided_by="Alice",
            reason="Approved for the Week 5 run-log demonstration.",
        )
        print(f"\n[{name}] paused for approval; Alice approved {request.id[:8]}")
        result = loop.resume(result)

    summary = load_index(logger.directory)[-1]
    path = logger.directory / summary["file"]
    shown = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
    print(f"\n=== {name}: {result.status.value} ({result.iterations} iterations)")
    print(f"saved: {shown}")
    print(format_run(load_run(path)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        help="where to save run logs (default: QA_AGENT_TRACE_DIR or evidence/traces/runs)",
    )
    args = parser.parse_args()

    logger = RunLogger(args.output_dir)
    runtime = Path(tempfile.mkdtemp(prefix="member5_run_log_demo_"))
    try:
        gate = JSONApprovalGate(
            store=JSONApprovalStore(str(runtime / "approval_queue.json")),
            audit=AuditLogger(str(runtime / "audit.log")),
            authorized_approvers={"Alice", "Bob"},
            trace_sink=logger,
        )

        run_scenario(
            "grounded-proposal",
            logger,
            gate,
            ScriptedPlanner(
                proposal(Action.READ_FILE, {"path": SOURCE}),
                propose_test(),
            ),
            cap=5,
        )

        run_scenario(
            "failure-recovery",
            logger,
            gate,
            ScriptedPlanner(
                proposal(
                    Action.PROPOSE_TEST,
                    {"title": "Discount applied twice"},
                    evidence=(FABRICATED,),
                ),
                proposal(
                    Action.RUN_TESTS,
                    {"test_node_ids": ["rm -rf /"], "session_id": "week5-demo"},
                ),
                propose_test(),
            ),
            cap=5,
        )

        session = "week5-demo-approval-pause-resume"
        run_scenario(
            "approval-pause-resume",
            logger,
            gate,
            ScriptedPlanner(
                run_failing_test(session),
                run_failing_test(session),
                proposal(Action.READ_FILE, {"path": SOURCE}),
            ),
            cap=3,
        )
    finally:
        shutil.rmtree(runtime, ignore_errors=True)

    print(f"\nindex: {logger.index_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
