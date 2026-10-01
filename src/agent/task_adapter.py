"""Turn an ``AgentTaskContract`` into what ``agent.loop`` consumes.

``build_agent_task`` supplies the goal from the static contract and the
identity from the caller; the contract never carries session, actor or role.
``build_stop_evaluator`` is an open seam: Member 1's ``stop_conditions.py``
does not exist yet, so it raises instead of faking enforcement.
"""

from __future__ import annotations

from agent.loop import AgentTask, StopEvaluator
from models.types import AgentTaskContract
from orchestrator import ExecutionContext


class StopEvaluatorNotImplementedError(NotImplementedError):
    """Member 1's stop evaluator (src/agent/stop_conditions.py) is not built yet."""


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
    """Build the stop evaluator from the contract's limits (not available yet).

    When stop_conditions.py lands, this must return an object satisfying
    ``agent.loop.StopEvaluator``::

        def evaluate(self, state: LoopState) -> StopReason | None

    constructed from ``contract.max_iterations`` and
    ``contract.wall_clock_budget_seconds``. It returns a ``StopReason`` to halt
    or ``None`` to allow another turn, and the loop calls it before the first
    turn and after every observation.
    """

    raise StopEvaluatorNotImplementedError(
        "src/agent/stop_conditions.py does not exist yet. The stop evaluator "
        "must implement evaluate(state: LoopState) -> StopReason | None and be "
        f"built from max_iterations={contract.max_iterations} and "
        f"wall_clock_budget_seconds={contract.wall_clock_budget_seconds}."
    )
