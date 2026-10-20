#!/usr/bin/env python3
"""Run one agent session end to end: build_agent_session with the real
RetrievalContextSensor and PromptPlanner.

Week 8, Member 3. Real: the shipped task contract (with the goal given here),
the stop policy, AgentLoop, BM25 retrieval over a corpus folder,
build_context, the four real tools, ToolDispatcher and validate_citations.
No approval gate is configured, so run_tests and draft_issue are always
refused (approval_gate_missing): this script can never run tests or save a
draft.

Without ``--live`` an offline stub client answers from the evidence it was
shown, and no model client is built, so no key is read and nothing is sent.
With ``--live`` the planner's client comes from ``config.build_model_client``
(MODEL_ENDPOINT, MODEL_API_KEY, MODEL_NAME in the environment). This script
never reads a .env file and never prints or writes the key.

Usage (Git Bash, from the repository root):
    python scripts/run_agent_session.py --goal "Propose a test that the account locks after five failed login attempts."
    python scripts/run_agent_session.py --goal "..." --live --out evidence/test-runs/week8/agent-session/run.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.planner import PromptPlanner  # noqa: E402
from agent.runner import build_agent_session  # noqa: E402
from agent.sensor import RetrievalContextSensor  # noqa: E402
from agent.task_contract import load_task_contract  # noqa: E402
from models.client import ModelCallResult, ModelIntegrationError, TokenUsage  # noqa: E402
from orchestrator import ToolDispatcher, ToolRegistry  # noqa: E402
from rag.injection_flagging import TRACE_ACTION  # noqa: E402
from rag.retrieval import build_retrieval_pipeline, load_documents_from_directory  # noqa: E402
from sandbox import SandboxExecutor  # noqa: E402
from tools import DraftIssueTool, DraftStore, ReadFileTool, RunTestsTool, SearchRepoTool  # noqa: E402

DEFAULT_CORPUS = REPO_ROOT / "tests" / "fixtures" / "member2" / "corpus"
OFFLINE_MODEL = "offline-stub-no-network"


class OfflineClient:
    """Dry-run client: proposes a test citing the evidence it was shown, or an
    evidence-free no_action when nothing was found. Not model output."""

    model = OFFLINE_MODEL

    def generate(self, *, system_prompt: str, user_content: str) -> ModelCallResult:
        paths = re.findall(r'<evidence source_path="([^"]+)"', user_content)
        if paths:
            reply = {
                "action": "propose_test", "arguments": {"title": "offline stub proposal"},
                "rationale": "Offline stub reply. Not model output.",
                "evidence": [{"source_path": p, "note": "stub"} for p in paths],
                "confidence": "low",
            }
        else:
            reply = {
                "action": "no_action", "arguments": {},
                "rationale": "Offline stub reply: no evidence was found.",
                "evidence": [], "confidence": "low",
            }
        return ModelCallResult(json.dumps(reply), OFFLINE_MODEL, 0, TokenUsage(0, 0, 0))


class MemorySink:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    def record(self, entry: Any) -> None:
        self.entries.append(entry)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def live_planner(**kwargs: Any) -> PromptPlanner:
    """The planner with the real configured client. Only called with --live."""

    return PromptPlanner.from_config(**kwargs)


def build_session(goal: str, corpus: Path, *, live: bool, sink: MemorySink):
    pipeline = build_retrieval_pipeline(load_documents_from_directory(corpus), corpus_version="session")
    dispatcher = ToolDispatcher(ToolRegistry([
        SearchRepoTool(pipeline),
        ReadFileTool(),
        RunTestsTool([], SandboxExecutor()),
        DraftIssueTool(DraftStore()),
    ]))
    if live:
        planner = live_planner(trace_sink=sink, clock=_utc_now)
    else:
        planner = PromptPlanner(OfflineClient(), trace_sink=sink, clock=_utc_now)
    contract = dataclasses.replace(load_task_contract(), goal=goal)
    session = build_agent_session(
        contract,
        session_id=f"session-{_utc_now().strftime('%Y%m%dT%H%M%SZ')}",
        actor_id="member3-cli",
        role="developer",
        # The loop records sensed-context flags itself (flag_trace_entry), so
        # the sensor gets no sink here; the planner still traces history flags.
        sensor=RetrievalContextSensor(pipeline),
        planner=planner,
        dispatcher=dispatcher,
        trace_sink=sink,
    )
    return session, planner


def summarize(result: Any, planner: PromptPlanner, sink: MemorySink, *, live: bool, goal: str) -> dict:
    proposal = result.proposal
    return {
        "live": live,
        "model": getattr(planner.client, "model", None),
        "prompt_version": planner.prompt.version,
        "goal": goal,
        "status": result.status.value,
        "failure": None if result.failure is None else result.failure.value,
        "planner_failure": None if planner.last_failure is None else planner.last_failure.value,
        "iterations": result.iterations,
        "final_action": None if proposal is None else proposal.action.value,
        "cited_paths": [] if proposal is None else [ref.source_path for ref in proposal.evidence],
        "flag_entries": [e.detail for e in sink.entries if e.action == TRACE_ACTION],
        "trace_actions": [e.action for e in sink.entries],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one agent session end to end.")
    parser.add_argument("--goal", default=None,
                        help="Task goal, also used as the retrieval query (default: the contract goal).")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--live", action="store_true",
                        help="Use the real configured model. Without it nothing is sent.")
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON summary file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    goal = args.goal or load_task_contract().goal
    sink = MemorySink()
    try:
        session, planner = build_session(goal, args.corpus, live=args.live, sink=sink)
    except ModelIntegrationError as exc:
        print(f"Could not start: {exc}", file=sys.stderr)
        return 2
    print("PLAN")
    print(f"  live: {'ON (real model calls)' if args.live else 'off (offline stub, no network)'}")
    print(f"  model: {getattr(planner.client, 'model', '?')}  prompt: {planner.prompt.version}")
    print(f"  corpus: {args.corpus}")
    print(f"  goal: {goal}")
    result = session.run()
    summary = summarize(result, planner, sink, live=args.live, goal=goal)
    print("RESULT")
    for key in ("status", "failure", "planner_failure", "iterations", "final_action", "cited_paths"):
        print(f"  {key}: {summary[key]}")
    print(f"  flag entries traced: {len(summary['flag_entries'])}")
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"  summary written to {args.out}")
    return 0 if result.status.value in ("completed", "no_action") else 1


if __name__ == "__main__":
    raise SystemExit(main())
