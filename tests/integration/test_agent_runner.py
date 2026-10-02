"""Contract -> adapter -> AgentLoop, end to end with the real shipped YAML.

The real contract, adapter, stop policy, AgentLoop, ToolDispatcher and
ToolRegistry are used. Only the sensor, planner, one tool and the trace sink
are scripted, because the live model and retrieval index are outside this
test. Nothing here calls a model or touches the network.
"""

from __future__ import annotations

import unittest

from agent.loop import AgentLoop, AgentTask, LoopStatus
from agent.runner import AgentSession, build_agent_session
from agent.stop_conditions import StopConditionPolicy
from agent.task_contract import load_task_contract
from models.types import (
    Action,
    Confidence,
    EvidenceRef,
    ProposalSet,
    StopReason,
)
from orchestrator import ToolDispatcher, ToolRegistry, ToolRisk
from rag import AssembledContext

SOURCE = "tests/fixtures/member2/corpus/src/login_service.py"
IDENTITY = {"session_id": "session-1", "actor_id": "dev-1", "role": "developer"}


class Sensor:
    def sense(self, task, state):
        return AssembledContext(
            text="<evidence>fixture</evidence>",
            chunks_used=1,
            chunks_dropped=0,
            not_in_corpus=False,
            allowed_source_paths=frozenset({SOURCE}),
        )


class NeverFinishingPlanner:
    """A different search every turn, so only the iteration cap can stop it."""

    def __init__(self) -> None:
        self.tasks: list[AgentTask] = []

    def plan(self, task, context, state):
        self.tasks.append(task)
        return _proposal(Action.SEARCH_REPO, {"query": f"q{len(self.tasks)}"})


class ProposeTestPlanner:
    def plan(self, task, context, state):
        return _proposal(Action.PROPOSE_TEST, {"title": "Lock after five failures"})


class CountingSearchTool:
    name = "search_repo"
    risk = ToolRisk.READ_ONLY
    allowed_roles = ("developer",)

    def __init__(self) -> None:
        self.runs = 0

    def validate_arguments(self, arguments):
        return dict(arguments)

    def run(self, arguments, context):
        self.runs += 1
        return {"matches": [f"{SOURCE}#{self.runs}"]}

    def validate_output(self, output):
        return dict(output)


class Sink:
    def __init__(self) -> None:
        self.entries = []

    def record(self, entry) -> None:
        self.entries.append(entry)


def _proposal(action, arguments):
    return ProposalSet(
        action=action,
        arguments=arguments,
        rationale="Grounded in the supplied context.",
        evidence=(EvidenceRef(source_path=SOURCE),),
        confidence=Confidence.HIGH,
    )


def _session(planner, tool=None, contract=None) -> AgentSession:
    registry = ToolRegistry([tool or CountingSearchTool()])
    return build_agent_session(
        contract or load_task_contract(),
        sensor=Sensor(),
        planner=planner,
        dispatcher=ToolDispatcher(registry),
        trace_sink=Sink(),
        **IDENTITY,
    )


class AgentSessionConstructionTests(unittest.TestCase):
    def test_builds_a_loop_and_task_from_the_real_contract(self) -> None:
        contract = load_task_contract()
        session = _session(ProposeTestPlanner())

        self.assertIsInstance(session.loop, AgentLoop)
        self.assertEqual(session.task.goal, contract.goal)
        self.assertEqual(session.task.context.session_id, "session-1")
        self.assertIsInstance(session.loop._stop_evaluator, StopConditionPolicy)
        self.assertEqual(
            session.loop._stop_evaluator.max_iterations, contract.max_iterations
        )

    def test_invalid_identity_and_non_contract_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_agent_session(
                load_task_contract(),
                **{**IDENTITY, "role": " "},
                sensor=Sensor(),
                planner=ProposeTestPlanner(),
                dispatcher=ToolDispatcher(ToolRegistry([CountingSearchTool()])),
                trace_sink=Sink(),
            )
        with self.assertRaises(TypeError):
            _session(ProposeTestPlanner(), contract={"goal": "x"})  # type: ignore[arg-type]


class AgentSessionRunTests(unittest.TestCase):
    def test_a_grounded_proposal_completes_in_one_turn(self) -> None:
        result = _session(ProposeTestPlanner()).run()

        self.assertEqual(result.status, LoopStatus.COMPLETED)
        self.assertEqual(result.iterations, 1)

    def test_the_goal_from_the_contract_reaches_the_planner(self) -> None:
        planner = NeverFinishingPlanner()
        _session(planner).run()

        self.assertEqual({task.goal for task in planner.tasks}, {load_task_contract().goal})

    def test_the_contracts_iteration_cap_halts_the_loop(self) -> None:
        contract = load_task_contract()
        tool = CountingSearchTool()
        result = _session(NeverFinishingPlanner(), tool).run()

        self.assertEqual(result.status, LoopStatus.HALTED)
        self.assertEqual(result.halt.reason, StopReason.ITERATION_CAP)
        self.assertEqual(result.halt.iteration_count, contract.max_iterations)
        self.assertEqual(tool.runs, contract.max_iterations)


if __name__ == "__main__":
    unittest.main()
