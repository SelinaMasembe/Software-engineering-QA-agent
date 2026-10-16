#!/usr/bin/env python3
"""Demonstrate Week 7 step telemetry on three offline agent-loop runs.

Everything except the model is a real project component: retrieval and the
context builder over the Member 2 fixture corpus, Member 3's search_repo
tool, the Week 4 ToolDispatcher, the Week 5 AgentLoop, Member 1's stop
policy built by Member 3's task adapter, and the propose_action prompt file
loaded by Member 3's prompt loader. ``DemoModelClient`` returns canned JSON
in place of a provider call, so the demo needs no API key or network.

The three scenarios are a grounded proposal after one tool call, a question
the corpus cannot answer, and a tool request the dispatcher rejects before
the agent recovers. Each run writes one telemetry file and the script prints
one JSON document with every run's summary. Assertions make a regression
exit nonzero.

Run from the repository root:
    python scripts/member2_observability_demo.py
    python scripts/member2_observability_demo.py --timeline
    python scripts/member2_observability_demo.py --output-dir /tmp/telemetry
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent import AgentLoop, LoopStatus  # noqa: E402
from agent.task_adapter import build_agent_task, build_stop_evaluator  # noqa: E402
from models.client import ModelCallResult, TokenUsage  # noqa: E402
from models.types import AgentTaskContract, ProposalSet  # noqa: E402
from observability.instrumentation import (  # noqa: E402
    ObservedModelClient,
    ObservedRetrievalPipeline,
    instrument_loop,
)
from observability.telemetry import (  # noqa: E402
    DEFAULT_TELEMETRY_DIR,
    JsonlStepSink,
    ObservabilityRecorder,
)
from orchestrator import ToolDispatcher, ToolRegistry  # noqa: E402
from prompts.loader import load_latest  # noqa: E402
from rag import (  # noqa: E402
    build_context,
    build_retrieval_pipeline,
    load_documents_from_directory,
)
from tools import SearchRepoTool  # noqa: E402

CORPUS = REPO_ROOT / "tests" / "fixtures" / "member2" / "corpus"
REQUIREMENT = "requirements/authentication.md"
SOURCE = "src/login_service.py"


def _response(action: str, arguments: dict, evidence: list[str]) -> str:
    return json.dumps(
        {
            "action": action,
            "arguments": arguments,
            "rationale": "Demo response grounded in the supplied context.",
            "evidence": [{"source_path": path} for path in evidence],
            "confidence": "high" if evidence else "low",
        }
    )


SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "grounded-proposal",
        "goal": "Propose tests for account lockout after failed login attempts.",
        "responses": [
            _response("search_repo", {"query": "lockout threshold"}, [REQUIREMENT]),
            _response(
                "propose_test",
                {"title": "Account locks after five failed attempts", "target": SOURCE},
                [REQUIREMENT, SOURCE],
            ),
        ],
        "expected": LoopStatus.COMPLETED,
    },
    {
        "name": "not-in-corpus",
        "goal": "Describe the refund policy for annual subscription plans.",
        "responses": [_response("no_action", {}, [])],
        "expected": LoopStatus.NO_ACTION,
    },
    {
        "name": "rejected-tool-recovery",
        "goal": "Propose tests for account lockout after failed login attempts.",
        "responses": [
            # ``scope`` is not a search_repo argument, so the dispatcher
            # rejects the request before the tool runs.
            _response("search_repo", {"query": "lockout", "scope": "src"}, [REQUIREMENT]),
            _response(
                "propose_test",
                {"title": "Lockout counter resets after success", "target": SOURCE},
                [REQUIREMENT],
            ),
        ],
        "expected": LoopStatus.COMPLETED,
    },
]


class DemoModelClient:
    """Demo adapter standing in for ChatCompletionsClient; returns canned JSON."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def generate(self, *, system_prompt: str, user_content: str) -> ModelCallResult:
        self.calls += 1
        raw = self.responses[self.calls - 1]
        prompt_tokens = (len(system_prompt) + len(user_content)) // 4
        return ModelCallResult(
            raw_text=raw,
            model="demo-offline-model",
            latency_ms=0,
            usage=TokenUsage(
                input_tokens=prompt_tokens,
                output_tokens=len(raw) // 4,
                total_tokens=prompt_tokens + len(raw) // 4,
            ),
            request_id=f"demo-{self.calls}",
        )


class RetrievalSensor:
    """Retrieves evidence for the task goal and builds the turn's context."""

    def __init__(self, pipeline: Any) -> None:
        self.pipeline = pipeline

    def sense(self, task: Any, state: Any) -> Any:
        return build_context(self.pipeline.retrieve(task.goal))


class PromptPlanner:
    """One propose_action call per turn, parsed by Member 1's ProposalSet."""

    def __init__(self, client: Any, system_prompt: str) -> None:
        self.client = client
        self.system_prompt = system_prompt

    def plan(self, task: Any, context: Any, state: Any) -> ProposalSet:
        result = self.client.generate(
            system_prompt=self.system_prompt,
            user_content=f"GOAL: {task.goal}\n\n{context.text}",
        )
        return ProposalSet.model_validate_json(result.raw_text)


class DemoTraceSink:
    """Keeps the loop's TraceEntry objects in memory for this demo only."""

    def __init__(self) -> None:
        self.entries: list[Any] = []

    def record(self, entry: Any) -> None:
        self.entries.append(entry)


def run_scenario(
    scenario: dict[str, Any], pipeline: Any, prompt: Any, sink: JsonlStepSink | None
) -> tuple[Any, ObservabilityRecorder]:
    session_id = f"week7-demo-{scenario['name']}"
    contract = AgentTaskContract(
        goal=scenario["goal"],
        tools=("search_repo",),
        max_iterations=4,
        wall_clock_budget_seconds=30.0,
    )
    recorder = ObservabilityRecorder(session_id, sinks=[] if sink is None else [sink])
    observed_pipeline = ObservedRetrievalPipeline(pipeline, recorder)
    client = ObservedModelClient(
        DemoModelClient(scenario["responses"]),
        recorder,
        prompt_id=prompt.prompt_id,
        prompt_version=prompt.version,
    )
    wrapped = instrument_loop(
        recorder,
        sensor=RetrievalSensor(observed_pipeline),
        planner=PromptPlanner(client, prompt.text),
        dispatcher=ToolDispatcher(ToolRegistry([SearchRepoTool(observed_pipeline)])),
        trace_sink=DemoTraceSink(),
        stop_evaluator=build_stop_evaluator(contract),
    )
    task = build_agent_task(
        contract, session_id=session_id, actor_id="demo-developer", role="developer"
    )
    result = AgentLoop(**wrapped.loop_kwargs()).run(task)
    return result, recorder


def _detail(kind: str, a: Any) -> str:
    if kind == "loop_event":
        return a.get("event", "")
    if kind == "stop_check":
        return a.get("decision") or "continue"
    if kind == "retrieval":
        return f"{a.get('chunks_returned')} chunks; not_in_corpus={a.get('not_in_corpus')}"
    if kind == "sense":
        return f"allowed_sources={len(a.get('allowed_sources', ()))}"
    if kind == "model_call":
        return f"{a.get('model')} {a.get('prompt_version')} tokens={a.get('total_tokens')}"
    if kind == "plan":
        return f"{a.get('action')} cites={len(a.get('evidence_traceable', ()))}"
    if kind == "tool_call":
        code = f" ({a['code']})" if a.get("code") else ""
        return f"{a.get('tool')} -> {a.get('status')}{code}"
    return ""


def timeline(recorder: ObservabilityRecorder) -> str:
    lines = [f"--- {recorder.session_id}"]
    for record in recorder.records:
        status = "ok" if record.ok else f"error={record.error_type}"
        lines.append(
            f"{record.seq:>3}  {record.kind.value:<11} {record.duration_ms:>9.3f} ms  "
            f"{status:<6} {_detail(record.kind.value, record.attributes)}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_TELEMETRY_DIR,
        help="where telemetry files are written (default: %(default)s)",
    )
    parser.add_argument(
        "--no-write", action="store_true", help="print summaries without writing files"
    )
    parser.add_argument(
        "--timeline", action="store_true", help="also print each run's step timeline"
    )
    args = parser.parse_args(argv)

    pipeline = build_retrieval_pipeline(
        load_documents_from_directory(CORPUS), corpus_version="member2-fixture"
    )
    prompt = load_latest("propose_action")
    sink = None if args.no_write else JsonlStepSink(args.output_dir)

    report: dict[str, Any] = {"prompt_version": prompt.version, "runs": []}
    for scenario in SCENARIOS:
        result, recorder = run_scenario(scenario, pipeline, prompt, sink)
        assert result.status is scenario["expected"], (scenario["name"], result.status)
        summary = recorder.summary()
        assert summary["errors"] == 0 and summary["dropped_writes"] == 0, summary
        path = None if sink is None else sink.path_for(recorder.session_id)
        report["runs"].append(
            {
                "scenario": scenario["name"],
                "status": result.status.value,
                "telemetry_file": None if path is None else _display(path),
                "summary": summary,
            }
        )
        if args.timeline:
            print(timeline(recorder), file=sys.stderr)

    by_name = {run["scenario"]: run["summary"] for run in report["runs"]}
    assert by_name["grounded-proposal"]["tools"]["by_status"] == {"executed": 1}
    assert by_name["not-in-corpus"]["retrieval"]["not_in_corpus"] == 1
    assert by_name["rejected-tool-recovery"]["tools"]["by_status"] == {"rejected": 1}

    print(json.dumps(report, indent=2))
    return 0


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
