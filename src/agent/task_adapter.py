"""Turn an ``AgentTaskContract`` into what ``agent.loop`` consumes.

``build_agent_task`` supplies the goal from the static contract and the
identity from the caller; the contract never carries session, actor or role.

``build_stop_evaluator`` was an open seam through Week 4: Member 1's
``stop_conditions.py`` did not exist yet, so it raised
``StopEvaluatorNotImplementedError`` instead of faking enforcement. Week 5
closes that seam: it now builds and returns a real
``agent.stop_conditions.StopConditionPolicy`` from the contract's
``max_iterations`` and ``wall_clock_budget_seconds``, the exact construction
the previous version's error message already described.

One caller responsibility this function cannot enforce by itself: the
returned policy is stateful (it tracks its own wall-clock start time once
``evaluate()`` is first called). The same instance must be reused across a
``run()`` and any later ``resume()`` of the same session; calling
``build_stop_evaluator`` again at resume time builds a fresh policy whose
clock restarts from that moment, which silently gives the session a new
wall-clock budget rather than continuing the original one.
"""

from __future__ import annotations

from agent.loop import AgentTask, StopEvaluator
from agent.stop_conditions import StopConditionPolicy
from models.types import AgentTaskContract
from orchestrator import ExecutionContext


def build_agent_task(
    contract: AgentTaskContract,
    *,
    session_id: str,
    actor_id: str,
    role: str,
) -> AgentTask:
    """Build the loop's ``AgentTask`` from the contract goal and runtime identity.

    Invalid identity values raise ``ValueError`` from ``ExecutionContext``.
    """

    if not isinstance(contract, AgentTaskContract):
        raise TypeError("build_agent_task requires an AgentTaskContract.")
    context = ExecutionContext(session_id=session_id, actor_id=actor_id, role=role)
    return AgentTask(goal=contract.goal, context=context)


def build_stop_evaluator(contract: AgentTaskContract) -> StopEvaluator:
    """Build the stop evaluator from the contract's limits.

    Returns a new ``StopConditionPolicy`` (``agent.stop_conditions``)
    constructed from ``contract.max_iterations`` and
    ``contract.wall_clock_budget_seconds``. It satisfies
    ``agent.loop.StopEvaluator``: ``evaluate(state: LoopState) -> StopReason |
    None``, returning a ``StopReason`` to halt or ``None`` to allow another
    turn. The loop calls it before the first turn of a session and after
    every recorded observation, never anywhere else.
    """

    if not isinstance(contract, AgentTaskContract):
        raise TypeError("build_stop_evaluator requires an AgentTaskContract.")
    return StopConditionPolicy.from_contract(contract)
