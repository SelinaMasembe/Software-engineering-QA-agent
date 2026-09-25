from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from orchestration.tool_dispatcher import ExecutionContext, ToolRisk


class RunTestsTool:
    name = "run_tests"
    risk = ToolRisk.REQUIRES_APPROVAL
    allowed_roles = ("developer", "qa_engineer", "maintainer")

    def __init__(self, sandbox_root: str, manifest: Mapping[str, tuple[str, ...]]) -> None:
        self.sandbox_root = Path(sandbox_root).resolve()
        self.manifest = dict(manifest)

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        node_ids = arguments.get("test_node_ids")
        session_id = arguments.get("session_id")

        if not isinstance(node_ids, list) or not node_ids:
            raise ValueError("test_node_ids must be a non-empty list.")
        if not all(isinstance(value, str) and value for value in node_ids):
            raise ValueError("test_node_ids must contain strings.")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id is required.")
        if any(node_id not in self.manifest for node_id in node_ids):
            raise ValueError("Unknown test node ID.")

        return {
            "test_node_ids": list(node_ids),
            "session_id": session_id,
        }

    def run(
        self,
        arguments: Mapping[str, Any],
        context: ExecutionContext,
    ) -> Mapping[str, Any]:
        results = []

        for node_id in arguments["test_node_ids"]:
            command = list(self.manifest[node_id])
            started = time.monotonic()

            completed = subprocess.run(
                command,
                cwd=self.sandbox_root,
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )

            results.append(
                {
                    "id": node_id,
                    "result": "pass" if completed.returncode == 0 else "fail",
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "stdout": completed.stdout[-4000:],
                    "stderr": completed.stderr[-4000:],
                }
            )

        status = (
            "pass"
            if all(item["result"] == "pass" for item in results)
            else "fail"
        )
        return {"status": status, "per_test": results}

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        if output.get("status") not in {"pass", "fail", "error"}:
            raise ValueError("Invalid test status.")
        if not isinstance(output.get("per_test"), list):
            raise ValueError("per_test must be a list.")
        return dict(output)


class DraftIssueTool:
    name = "draft_issue"
    risk = ToolRisk.READ_ONLY
    allowed_roles = ("developer", "qa_engineer", "maintainer")

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "issue_drafts.json"

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        title = arguments.get("title")
        body = arguments.get("body")
        evidence_refs = arguments.get("evidence_refs")

        if not isinstance(title, str) or not title.strip():
            raise ValueError("title is required.")
        if not isinstance(body, str) or not body.strip():
            raise ValueError("body is required.")
        if not isinstance(evidence_refs, list):
            raise ValueError("evidence_refs must be a list.")
        if not all(isinstance(value, str) for value in evidence_refs):
            raise ValueError("evidence_refs must contain strings.")

        return {
            "title": title,
            "body": body,
            "evidence_refs": list(evidence_refs),
        }

    def run(
        self,
        arguments: Mapping[str, Any],
        context: ExecutionContext,
    ) -> Mapping[str, Any]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        drafts = []

        if self.path.exists():
            content = self.path.read_text(encoding="utf-8").strip()
            drafts = json.loads(content) if content else []

        draft = {
            "draft_id": str(uuid.uuid4()),
            "title": arguments["title"],
            "body": arguments["body"],
            "evidence_refs": arguments["evidence_refs"],
            "status": "draft",
        }
        drafts.append(draft)
        self.path.write_text(json.dumps(drafts, indent=2), encoding="utf-8")

        return {
            "draft_id": draft["draft_id"],
            "status": "draft",
        }

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(output.get("draft_id"), str):
            raise ValueError("Invalid draft ID.")
        if output.get("status") != "draft":
            raise ValueError("Draft must not be submitted.")
        return dict(output)