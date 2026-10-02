#!/usr/bin/env python3
"""Run src/agent/stop_conditions.py against four realistic session traces.

This is a development smoke runner (see scripts/member1_types_smoke.py and
scripts/member2_model_smoke.py for the same pattern applied to earlier
weeks), not part of the automated test suite. It answers one question: does
the real StopConditionPolicy actually halt a session for each of US-9's four
stop conditions, using the same LoopState/Observation shapes
agent.loop.AgentLoop produces, not only the synthetic fixtures in
tests/test_stop_conditions.py?

Four traces are built below, one per StopReason:
  1. A session that stays under every limit (no halt - included so the
     "everything is fine" case is shown too, not only the failure modes).
  2. A session that reaches the contract's max_iterations.
  3. A session whose wall-clock budget runs out, using a fake clock so this
     script does not actually sleep.
  4. A session where the same (action, arguments) pair is proposed twice.
  5. A session where two consecutive tool calls return identical output.

Each trace is fed to policy.evaluate() the same way AgentLoop calls it: once
before the first turn, then again after every recorded observation, stopping
at the first StopReason returned.

Usage:
    python scripts/member1_stop_conditions_smoke.py
(No PYTHONPATH setup needed - this script adds src/ to sys.path itself.)
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent.loop import LoopState, Observation, ObservationKind, PlannedAction  # noqa: E402
from agent.stop_conditions import StopConditionPolicy  # noqa: E402
from agent.task_contract import load_task_contract  # noqa: E402
from models.types import Action, Confidence, StopReason  # noqa: E402


class _ScriptedClock:
    """A clock this script advances by hand, so the wall-clock trace does
    not require actually waiting out the real budget."""

    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self._now


def _turn(
    iteration: int,
    *,
    action: Action = Action.SEARCH_REPO,
    arguments: dict | None = None,
    output: dict | None = None,
) -> Observation:
    proposal = PlannedAction(
        action=action,
        arguments={"query": f"turn-{iteration}"} if arguments is None else arguments,
        rationale="demonstration turn for the smoke script",
        evidence=(),
        confidence=Confidence.HIGH,
    )
    return Observation(
        iteration=iteration,
        proposal=proposal,
        kind=ObservationKind.TOOL_EXECUTED,
        message="ok",
        output={"result": f"turn-{iteration}"} if output is None else output,
    )


def _run_trace(label: str, policy: StopConditionPolicy, turns: list[Observation]) -> None:
    print(f"\n{label}")
    state = LoopState(session_id="smoke-session")

    reason = policy.evaluate(state)
    if reason is not None:
        print(f"  before any turn: HALTED -> {reason.value}")
        return
    print("  before any turn: continue")

    for turn in turns:
        state = state._with(turn)
        reason = policy.evaluate(state)
        if reason is not None:
            print(f"  after turn {turn.iteration}: HALTED -> {reason.value}")
            return
        print(f"  after turn {turn.iteration}: continue")

    print("  all turns finished: no stop condition was reached")


def main() -> int:
    contract = load_task_contract()
    print(
        f"Loaded the shipped contract: max_iterations={contract.max_iterations}, "
        f"wall_clock_budget_seconds={contract.wall_clock_budget_seconds}"
    )

    # 1. Healthy session: three distinct turns, well under the contract's
    # own limits. No halt expected.
    healthy_policy = StopConditionPolicy.from_contract(contract)
    _run_trace(
        "Trace 1: a normal session that never reaches a limit",
        healthy_policy,
        [_turn(1), _turn(2), _turn(3)],
    )

    # 2. Iteration cap: force a small cap so the demonstration does not need
    # five real turns.
    cap_policy = StopConditionPolicy(
        max_iterations=2, wall_clock_budget_seconds=contract.wall_clock_budget_seconds
    )
    _run_trace(
        "Trace 2: iteration cap (max_iterations=2 for this trace)",
        cap_policy,
        [_turn(1), _turn(2), _turn(3)],
    )

    # 3. Wall-clock budget: a scripted clock stands in for real time, so the
    # script advances past a 60-second budget without waiting 60 seconds.
    clock = _ScriptedClock()
    wall_clock_policy = StopConditionPolicy(
        max_iterations=10, wall_clock_budget_seconds=60, clock=clock
    )
    print("\nTrace 3: wall-clock budget (60s budget for this trace, scripted clock)")
    state = LoopState(session_id="smoke-session")
    print(f"  before any turn: {wall_clock_policy.evaluate(state) or 'continue'}")
    clock.advance(65)
    state = state._with(_turn(1))
    reason = wall_clock_policy.evaluate(state)
    print(f"  after turn 1 (65s elapsed): HALTED -> {reason.value}" if reason else "  after turn 1: continue")

    # 4. Repeated call: the identical action and arguments proposed twice in
    # a row. This check only compares a proposal against the one immediately
    # before it, not the whole history, so the repeat has to be consecutive;
    # see src/agent/stop_conditions.py's module docstring for why.
    repeat_policy = StopConditionPolicy.from_contract(contract)
    _run_trace(
        "Trace 4: repeated call (identical action and arguments, back to back)",
        repeat_policy,
        [
            _turn(1, action=Action.SEARCH_REPO, arguments={"query": "login lockout"}),
            _turn(2, action=Action.SEARCH_REPO, arguments={"query": "login lockout"}),
        ],
    )

    # 5. No new information: two consecutive calls to the same tool return
    # byte-for-byte identical output, even though the arguments differ.
    stale_policy = StopConditionPolicy.from_contract(contract)
    _run_trace(
        "Trace 5: no new information (same tool, identical output twice)",
        stale_policy,
        [
            _turn(1, arguments={"query": "a"}, output={"result": "no matches"}),
            _turn(2, arguments={"query": "b"}, output={"result": "no matches"}),
        ],
    )

    print(
        "\nAll five traces ran against the real StopConditionPolicy "
        "(src/agent/stop_conditions.py), not a stand-in - compare the "
        "halted reasons above against tests/test_stop_conditions.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
