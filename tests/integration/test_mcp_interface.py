"""Contract tests for the Week 6 Member 2 MCP-style interface."""

from __future__ import annotations

import json
import unittest

from integration import (
    CAPABILITIES,
    INTERFACE_ID,
    CapabilityEffect,
    CapabilityPermissionError,
    UnknownCapabilityError,
    describe_interface,
    require_capability,
)


class InterfaceDescriptionTests(unittest.TestCase):
    def test_description_is_versioned_json_and_detached(self) -> None:
        first = describe_interface()
        self.assertEqual(first["interface"], INTERFACE_ID)
        json.dumps(first)

        first["capabilities"][0]["name"] = "changed"
        second = describe_interface()
        self.assertEqual(second["capabilities"][0]["name"], "qa_memory.get_record")

    def test_capabilities_have_unique_names_and_closed_object_schemas(self) -> None:
        names = [capability.name for capability in CAPABILITIES]
        self.assertEqual(len(names), len(set(names)))
        for capability in CAPABILITIES:
            for schema in (capability.input_schema, capability.output_schema):
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])

    def test_external_session_state_is_read_only(self) -> None:
        state_capabilities = [
            capability for capability in CAPABILITIES if capability.name.startswith("qa_state.")
        ]

        self.assertEqual([item.name for item in state_capabilities], ["qa_state.get_session"])
        self.assertTrue(
            all(item.effect is CapabilityEffect.READ_ONLY for item in state_capabilities)
        )

    def test_mutating_memory_calls_require_revision_or_create_intent(self) -> None:
        store = next(item for item in CAPABILITIES if item.name.endswith("store_record"))
        delete = next(item for item in CAPABILITIES if item.name.endswith("delete_record"))

        self.assertIn("expected_revision", store.input_schema["required"])
        self.assertIn("expected_revision", delete.input_schema["required"])
        self.assertEqual(store.permission, "memory:write")
        self.assertEqual(delete.permission, "memory:delete")

    def test_security_boundary_explicitly_preserves_human_control(self) -> None:
        boundary = " ".join(describe_interface()["securityBoundary"]).lower()

        self.assertIn("human approval", boundary)
        self.assertIn("no capability resumes", boundary)
        self.assertIn("schema validation", boundary)


class CapabilityPermissionTests(unittest.TestCase):
    def test_exact_permission_allows_capability_resolution(self) -> None:
        capability = require_capability("qa_memory.get_record", {"memory:read"})

        self.assertEqual(capability.name, "qa_memory.get_record")

    def test_missing_permission_is_rejected(self) -> None:
        with self.assertRaises(CapabilityPermissionError):
            require_capability("qa_memory.store_record", {"memory:read"})

    def test_unknown_capability_is_rejected(self) -> None:
        with self.assertRaises(UnknownCapabilityError):
            require_capability("qa_agent.execute_tool", {"memory:read"})


if __name__ == "__main__":
    unittest.main()
