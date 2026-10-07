"""Versioned MCP-style contract for memory and session-state integration.

This module defines capabilities, JSON inputs and outputs, permissions, and
the security boundary.  It deliberately does not provide a network server or
call ``memory.store.MemoryStore`` directly.  A transport adapter can publish
these descriptions through MCP, while Member 3's ``memory.api`` remains the
application boundary that validates Member 1's record schema and applies the
memory-use policy.

External callers may read workflow state but cannot change it.  No capability
can approve a request, resume an agent, dispatch a tool, or execute an action.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Collection, Mapping


INTERFACE_ID = "qa-agent.memory-interface/v1"


class CapabilityEffect(str, Enum):
    """Whether a capability can change persistent memory."""

    READ_ONLY = "read_only"
    MUTATING = "mutating"


class UnknownCapabilityError(LookupError):
    """The requested capability is not part of this interface version."""


class CapabilityPermissionError(PermissionError):
    """The caller lacks the exact scope required by a capability."""


@dataclass(frozen=True)
class CapabilitySpec:
    """One transport-neutral tool declaration compatible with MCP tooling."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    permission: str
    effect: CapabilityEffect

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible capability description."""

        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": _thaw(self.input_schema),
            "outputSchema": _thaw(self.output_schema),
            "permission": self.permission,
            "effect": self.effect.value,
        }


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return copy.deepcopy(value)


def _object_schema(
    properties: Mapping[str, Any], required: tuple[str, ...]
) -> Mapping[str, Any]:
    return _freeze(
        {
            "type": "object",
            "properties": dict(properties),
            "required": list(required),
            "additionalProperties": False,
        }
    )


_RECORD_ENVELOPE = {
    "type": "object",
    "properties": {
        "namespace": {"type": "string", "minLength": 1},
        "record_id": {"type": "string", "minLength": 1},
        "record": {"type": "object"},
        "revision": {"type": "integer", "minimum": 0},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "expires_at": {
            "anyOf": [
                {"type": "string", "format": "date-time"},
                {"type": "null"},
            ]
        },
    },
    "required": [
        "namespace",
        "record_id",
        "record",
        "revision",
        "created_at",
        "updated_at",
        "expires_at",
    ],
    "additionalProperties": False,
}

_SESSION_STATE = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "minLength": 1},
        "phase": {
            "type": "string",
            "enum": [
                "created",
                "running",
                "awaiting_approval",
                "completed",
                "halted",
                "failed",
            ],
        },
        "iteration_count": {"type": "integer", "minimum": 0},
        "revision": {"type": "integer", "minimum": 0},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "pending_approval_id": {
            "anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]
        },
    },
    "required": [
        "session_id",
        "phase",
        "iteration_count",
        "revision",
        "created_at",
        "updated_at",
        "pending_approval_id",
    ],
    "additionalProperties": False,
}


def _capabilities() -> tuple[CapabilitySpec, ...]:
    nullable_record = {"anyOf": [_RECORD_ENVELOPE, {"type": "null"}]}
    return (
        CapabilitySpec(
            name="qa_memory.get_record",
            description="Read one validated memory record by namespace and identifier.",
            input_schema=_object_schema(
                {
                    "namespace": {"type": "string", "minLength": 1},
                    "record_id": {"type": "string", "minLength": 1},
                },
                ("namespace", "record_id"),
            ),
            output_schema=_object_schema({"record": nullable_record}, ("record",)),
            permission="memory:read",
            effect=CapabilityEffect.READ_ONLY,
        ),
        CapabilitySpec(
            name="qa_memory.list_records",
            description="List a bounded set of validated records in one namespace.",
            input_schema=_object_schema(
                {
                    "namespace": {"type": "string", "minLength": 1},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 50,
                    },
                },
                ("namespace",),
            ),
            output_schema=_object_schema(
                {
                    "records": {"type": "array", "items": _RECORD_ENVELOPE},
                    "truncated": {"type": "boolean"},
                },
                ("records", "truncated"),
            ),
            permission="memory:read",
            effect=CapabilityEffect.READ_ONLY,
        ),
        CapabilitySpec(
            name="qa_memory.store_record",
            description=(
                "Create or revision-check a record after application-level schema "
                "and data-policy validation."
            ),
            input_schema=_object_schema(
                {
                    "namespace": {"type": "string", "minLength": 1},
                    "record_id": {"type": "string", "minLength": 1},
                    "record": {"type": "object"},
                    "expires_at": {
                        "anyOf": [
                            {"type": "string", "format": "date-time"},
                            {"type": "null"},
                        ]
                    },
                    "expected_revision": {
                        "anyOf": [
                            {"type": "integer", "minimum": 0},
                            {"type": "null"},
                        ]
                    },
                },
                (
                    "namespace",
                    "record_id",
                    "record",
                    "expires_at",
                    "expected_revision",
                ),
            ),
            output_schema=_object_schema({"record": _RECORD_ENVELOPE}, ("record",)),
            permission="memory:write",
            effect=CapabilityEffect.MUTATING,
        ),
        CapabilitySpec(
            name="qa_memory.delete_record",
            description=(
                "Delete one record at an expected revision for an authorized "
                "retention or administrative process."
            ),
            input_schema=_object_schema(
                {
                    "namespace": {"type": "string", "minLength": 1},
                    "record_id": {"type": "string", "minLength": 1},
                    "expected_revision": {"type": "integer", "minimum": 0},
                },
                ("namespace", "record_id", "expected_revision"),
            ),
            output_schema=_object_schema({"deleted": {"type": "boolean"}}, ("deleted",)),
            permission="memory:delete",
            effect=CapabilityEffect.MUTATING,
        ),
        CapabilitySpec(
            name="qa_state.get_session",
            description="Read the current durable lifecycle state of one session.",
            input_schema=_object_schema(
                {"session_id": {"type": "string", "minLength": 1}},
                ("session_id",),
            ),
            output_schema=_object_schema(
                {
                    "state": {
                        "anyOf": [_SESSION_STATE, {"type": "null"}],
                    }
                },
                ("state",),
            ),
            permission="state:read",
            effect=CapabilityEffect.READ_ONLY,
        ),
    )


CAPABILITIES: tuple[CapabilitySpec, ...] = _capabilities()
_CAPABILITIES_BY_NAME = MappingProxyType(
    {capability.name: capability for capability in CAPABILITIES}
)

_SECURITY_BOUNDARY = (
    "The transport authenticates every caller and maps its identity to explicit scopes.",
    "memory.schema validation and the data-handling policy run before every write.",
    "Memory is advisory context and can never count as human approval.",
    "No capability resumes a session, dispatches a tool, or executes an action.",
    "Session state is externally readable but writable only by the trusted agent runtime.",
    "Deployments must protect project data in transit and audit capability calls.",
)


def require_capability(
    name: str, caller_permissions: Collection[str]
) -> CapabilitySpec:
    """Resolve a capability only when the caller has its exact scope."""

    if not isinstance(name, str) or not name.strip():
        raise UnknownCapabilityError("A capability name is required.")
    capability = _CAPABILITIES_BY_NAME.get(name)
    if capability is None:
        raise UnknownCapabilityError(f"Unknown capability: {name}.")
    if isinstance(caller_permissions, str):
        raise CapabilityPermissionError("Caller permissions must be a collection.")
    if capability.permission not in caller_permissions:
        raise CapabilityPermissionError(
            f"Capability requires the {capability.permission!r} permission."
        )
    return capability


def describe_interface() -> dict[str, Any]:
    """Return the complete versioned contract as detached JSON data."""

    return {
        "interface": INTERFACE_ID,
        "style": "MCP tools",
        "transport": "adapter-defined",
        "capabilities": [capability.to_dict() for capability in CAPABILITIES],
        "securityBoundary": list(_SECURITY_BOUNDARY),
    }
