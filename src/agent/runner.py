"""Drive ``agent.loop.AgentLoop`` from an ``AgentTaskContract``.

This module only composes existing pieces and does not change ``loop.py``:
``task_adapter`` builds the ``AgentTask`` and the stop evaluator from the
contract, and the caller supplies the runtime collaborators the contract
cannot describe (sensor, planner, dispatcher, trace sink) and the session
identity. ``AgentLoop`` keeps the one stop evaluator it was built with, so
``resume`` reuses it and the wall-clock budget is not reset.

The contract's ``tools`` list is not enforced here. Which tools may run is
decided by the ``ToolRegistry`` behind the dispatcher the caller passes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from agent.loop import (
    AgentLoop,
    AgentTask,
    ContextSensor,
    Dispatcher,
    LoopResult,
    Planner,
    TraceSink,
)
from agent.task_adapter import build_agent_task, build_stop_evaluator
from models.types import AgentTaskContract


@dataclass(frozen=True)
class AgentSession:
    """One contract-configured loop and the task it runs."""

    loop: AgentLoop
    task: AgentTask

    def run(self) -> LoopResult:
        return self.loop.run(self.task)

    def resume(self, paused: LoopResult) -> LoopResult:
        return self.loop.resume(paused)


def build_agent_session(
    contract: AgentTaskContract,
    *,
    session_id: str,
    actor_id: str,
    role: str,
    sensor: ContextSensor,
    planner: Planner,
    dispatcher: Dispatcher,
    trace_sink: TraceSink,
    clock: Callable[[], datetime] | None = None,
) -> AgentSession:
    """Build a loop whose goal and stop limits come from ``contract``.

    ``clock`` is passed to ``AgentLoop`` only when given, so the loop's own
    default applies otherwise.
    """

    task = build_agent_task(
        contract, session_id=session_id, actor_id=actor_id, role=role
    )
    options = {} if clock is None else {"clock": clock}
    loop = AgentLoop(
        sensor=sensor,
        planner=planner,
        dispatcher=dispatcher,
        stop_evaluator=build_stop_evaluator(contract),
        trace_sink=trace_sink,
        **options,
    )
    return AgentSession(loop=loop, task=task)
