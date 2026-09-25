"""Route one model-proposed tool request through the application boundary.

This module is the Week 4 Member 2 integration boundary. It does not implement tools,
tool schemas, approval policy, or an agent loop.  Instead, it connects those
separate contributions through small protocols and denies execution whenever a
required dependency is missing.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from enum import Enum
from time import perf_counter
from typing import Any, Collection, Iterable, Mapping, Protocol

from models.client import ModelResponseError
from models.types import Action, ProposalSet


TOOL_ACTIONS = frozenset(
    {
        Action.SEARCH_REPO,
        Action.READ_FILE,
        Action.RUN_TESTS,
        Action.DRAFT_ISSUE,
    }
)


class ToolRisk(str, Enum):
    """Execution controls declared by the owner of a tool specification."""

    READ_ONLY = "read_only"
    REQUIRES_APPROVAL = "requires_approval"


class ApprovalStatus(str, Enum):
    """Possible decisions returned by the injected approval gate."""

    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"


class DispatchStatus(str, Enum):
    """High-level outcome of one dispatch attempt."""

    EXECUTED = "executed"
    REJECTED = "rejected"
    AWAITING_APPROVAL = "awaiting_approval"
    NOT_A_TOOL = "not_a_tool"
    TOOL_ERROR = "tool_error"


class DispatchCode(str, Enum):
    """Stable machine-readable reason for a non-successful outcome."""

    MALFORMED_REQUEST = "malformed_request"
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    UNAUTHORIZED = "unauthorized"
    APPROVAL_GATE_MISSING = "approval_gate_missing"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_PENDING = "approval_pending"
    APPROVAL_UNAVAILABLE = "approval_unavailable"
    EXECUTION_FAILED = "execution_failed"
    INVALID_OUTPUT = "invalid_output"


class ToolRegistryError(ValueError):
    """Raised when a tool cannot be safely registered."""


@dataclass(frozen=True)
class ExecutionContext:
    """Identity and session data used for authorization and approval checks."""

    session_id: str
    actor_id: str
    role: str

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("Execution context requires a session ID.")
        if not isinstance(self.actor_id, str) or not self.actor_id.strip():
            raise ValueError("Execution context requires an actor ID.")
        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("Execution context requires a role.")
        if self.session_id != self.session_id.strip():
            raise ValueError("Execution context session ID must not contain padding.")
        if self.actor_id != self.actor_id.strip():
            raise ValueError("Execution context actor ID must not contain padding.")
        if self.role != self.role.strip():
            raise ValueError("Execution context role must not contain padding.")


@dataclass(frozen=True)
class ApprovalVerdict:
    """Normalized decision supplied by Member 5's approval gate."""

    status: ApprovalStatus


class Tool(Protocol):
    """Contract implemented by each Member 3 tool and its schemas."""

    name: str
    risk: ToolRisk
    allowed_roles: Collection[str]

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and normalize model-supplied arguments."""

    def run(
        self,
        arguments: Mapping[str, Any],
        context: ExecutionContext,
    ) -> Mapping[str, Any]:
        """Execute the tool once and return its raw structured output."""

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and normalize the tool's output schema."""


class ApprovalGate(Protocol):
    """Contract implemented by Member 5's approval-gate component."""

    def check(
        self,
        *,
        action: Action,
        arguments: Mapping[str, Any],
        context: ExecutionContext,
    ) -> ApprovalVerdict:
        """Return the current approval decision for this request."""


@dataclass(frozen=True)
class DispatchResult:
    """Safe application observation produced by one dispatch attempt."""

    status: DispatchStatus
    action: Action | None
    message: str
    latency_ms: int
    code: DispatchCode | None = None
    output: dict[str, Any] | None = None
    proposal: ProposalSet | None = None

    @property
    def executed(self) -> bool:
        return self.status is DispatchStatus.EXECUTED

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation suitable for demos and APIs."""

        return {
            "status": self.status.value,
            "action": self.action.value if self.action else None,
            "code": self.code.value if self.code else None,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "output": deepcopy(self.output),
        }


@dataclass(frozen=True)
class _RegisteredTool:
    action: Action
    risk: ToolRisk
    allowed_roles: frozenset[str]
    implementation: Tool


class ToolRegistry:
    """Immutable allow-list of the tool implementations available to dispatch."""

    def __init__(self, tools: Iterable[Tool]) -> None:
        registered: dict[Action, _RegisteredTool] = {}
        for tool in tools:
            try:
                action = Action(tool.name)
            except (AttributeError, ValueError) as exc:
                raise ToolRegistryError("A tool has an unknown action name.") from exc
            if action not in TOOL_ACTIONS:
                raise ToolRegistryError(
                    f"Action {action.value!r} is not an executable tool."
                )
            if action in registered:
                raise ToolRegistryError(
                    f"Tool {action.value!r} is registered more than once."
                )

            try:
                risk = ToolRisk(tool.risk)
                if isinstance(tool.allowed_roles, str):
                    raise TypeError(
                        "Allowed roles must be a collection of complete role names."
                    )
                allowed_roles = frozenset(
                    role.strip() for role in tool.allowed_roles if role.strip()
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise ToolRegistryError(
                    f"Tool {action.value!r} has invalid access metadata."
                ) from exc
            if not allowed_roles:
                raise ToolRegistryError(
                    f"Tool {action.value!r} must declare at least one allowed role."
                )

            registered[action] = _RegisteredTool(
                action=action,
                risk=risk,
                allowed_roles=allowed_roles,
                implementation=tool,
            )

        self._tools = registered

    @property
    def actions(self) -> frozenset[Action]:
        return frozenset(self._tools)

    def resolve(self, action: Action) -> _RegisteredTool | None:
        return self._tools.get(action)


class ToolDispatcher:
    """Validate and execute at most one approved tool request."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        approval_gate: ApprovalGate | None = None,
        max_output_bytes: int = 64_000,
    ) -> None:
        if max_output_bytes <= 0:
            raise ValueError("Maximum tool-output size must be greater than zero.")
        self.registry = registry
        self.approval_gate = approval_gate
        self.max_output_bytes = max_output_bytes

    def dispatch_raw(
        self,
        raw_model_response: str,
        *,
        context: ExecutionContext,
    ) -> DispatchResult:
        """Parse a raw model response and dispatch its single proposed action."""

        started = perf_counter()
        if not isinstance(raw_model_response, str):
            return self._result(
                started,
                status=DispatchStatus.REJECTED,
                action=None,
                code=DispatchCode.MALFORMED_REQUEST,
                message="The model response is not a valid tool request.",
            )
        try:
            proposal = ProposalSet.model_validate_json(raw_model_response)
        except ModelResponseError:
            return self._result(
                started,
                status=DispatchStatus.REJECTED,
                action=None,
                code=DispatchCode.MALFORMED_REQUEST,
                message="The model response is not a valid tool request.",
            )
        return self.dispatch(proposal, context=context, _started=started)

    def dispatch(
        self,
        proposal: ProposalSet,
        *,
        context: ExecutionContext,
        _started: float | None = None,
    ) -> DispatchResult:
        """Dispatch one structurally validated proposal."""

        started = perf_counter() if _started is None else _started
        try:
            action = Action(proposal.action)
            safe_proposal = replace(
                proposal,
                action=action,
                arguments=deepcopy(proposal.arguments),
            )
        except Exception:
            return self._result(
                started,
                status=DispatchStatus.REJECTED,
                action=None,
                code=DispatchCode.MALFORMED_REQUEST,
                message="The proposal is not a valid tool request.",
            )

        if action not in TOOL_ACTIONS:
            return self._result(
                started,
                status=DispatchStatus.NOT_A_TOOL,
                action=action,
                message="The proposed action does not require tool execution.",
                proposal=safe_proposal,
            )

        registered = self.registry.resolve(action)
        if registered is None:
            return self._result(
                started,
                status=DispatchStatus.REJECTED,
                action=action,
                code=DispatchCode.UNKNOWN_TOOL,
                message="The requested tool is not registered.",
                proposal=safe_proposal,
            )

        if context.role not in registered.allowed_roles:
            return self._result(
                started,
                status=DispatchStatus.REJECTED,
                action=action,
                code=DispatchCode.UNAUTHORIZED,
                message="The requester is not authorized to use this tool.",
                proposal=safe_proposal,
            )

        try:
            validated_arguments = registered.implementation.validate_arguments(
                deepcopy(safe_proposal.arguments)
            )
            if not isinstance(validated_arguments, dict):
                raise TypeError("Validated arguments must be a dictionary.")
        except Exception:
            return self._result(
                started,
                status=DispatchStatus.REJECTED,
                action=action,
                code=DispatchCode.INVALID_ARGUMENTS,
                message="The tool arguments are invalid.",
                proposal=safe_proposal,
            )

        if registered.risk is ToolRisk.REQUIRES_APPROVAL:
            approval_result = self._check_approval(
                registered,
                validated_arguments,
                context,
                started,
                safe_proposal,
            )
            if approval_result is not None:
                return approval_result

        try:
            raw_output = registered.implementation.run(
                deepcopy(validated_arguments), context
            )
        except Exception:
            return self._result(
                started,
                status=DispatchStatus.TOOL_ERROR,
                action=action,
                code=DispatchCode.EXECUTION_FAILED,
                message="The tool could not complete the request.",
                proposal=safe_proposal,
            )

        try:
            if not isinstance(raw_output, Mapping):
                raise TypeError("Tool output must be a mapping.")
            output = registered.implementation.validate_output(deepcopy(raw_output))
            if not isinstance(output, dict):
                raise TypeError("Validated tool output must be a dictionary.")
            encoded_output = json.dumps(
                output,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded_output) > self.max_output_bytes:
                raise ValueError("Tool output is too large.")
        except Exception:
            return self._result(
                started,
                status=DispatchStatus.TOOL_ERROR,
                action=action,
                code=DispatchCode.INVALID_OUTPUT,
                message="The tool returned an invalid response.",
                proposal=safe_proposal,
            )

        return self._result(
            started,
            status=DispatchStatus.EXECUTED,
            action=action,
            message="The tool executed successfully.",
            output=deepcopy(output),
            proposal=safe_proposal,
        )

    def _check_approval(
        self,
        registered: _RegisteredTool,
        arguments: dict[str, Any],
        context: ExecutionContext,
        started: float,
        proposal: ProposalSet,
    ) -> DispatchResult | None:
        if self.approval_gate is None:
            return self._result(
                started,
                status=DispatchStatus.REJECTED,
                action=registered.action,
                code=DispatchCode.APPROVAL_GATE_MISSING,
                message="The tool requires approval, but no approval gate is configured.",
                proposal=proposal,
            )

        try:
            verdict = self.approval_gate.check(
                action=registered.action,
                arguments=deepcopy(arguments),
                context=context,
            )
            status = ApprovalStatus(verdict.status)
        except Exception:
            return self._result(
                started,
                status=DispatchStatus.REJECTED,
                action=registered.action,
                code=DispatchCode.APPROVAL_UNAVAILABLE,
                message="The approval decision could not be obtained.",
                proposal=proposal,
            )

        if status is ApprovalStatus.APPROVED:
            return None
        if status is ApprovalStatus.PENDING:
            return self._result(
                started,
                status=DispatchStatus.AWAITING_APPROVAL,
                action=registered.action,
                code=DispatchCode.APPROVAL_PENDING,
                message="The tool request is waiting for human approval.",
                proposal=proposal,
            )
        return self._result(
            started,
            status=DispatchStatus.REJECTED,
            action=registered.action,
            code=DispatchCode.APPROVAL_DENIED,
            message="The tool request was not approved.",
            proposal=proposal,
        )

    @staticmethod
    def _result(
        started: float,
        *,
        status: DispatchStatus,
        action: Action | None,
        message: str,
        code: DispatchCode | None = None,
        output: dict[str, Any] | None = None,
        proposal: ProposalSet | None = None,
    ) -> DispatchResult:
        return DispatchResult(
            status=status,
            action=action,
            code=code,
            message=message,
            latency_ms=round((perf_counter() - started) * 1_000),
            output=output,
            proposal=proposal,
        )
