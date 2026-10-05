"""External integration contracts for the QA agent."""

from .mcp_interface import (
    CAPABILITIES,
    INTERFACE_ID,
    CapabilityEffect,
    CapabilityPermissionError,
    CapabilitySpec,
    UnknownCapabilityError,
    describe_interface,
    require_capability,
)

__all__ = [
    "CAPABILITIES",
    "INTERFACE_ID",
    "CapabilityEffect",
    "CapabilityPermissionError",
    "CapabilitySpec",
    "UnknownCapabilityError",
    "describe_interface",
    "require_capability",
]
