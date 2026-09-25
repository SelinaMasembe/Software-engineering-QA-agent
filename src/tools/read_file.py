"""The read_file tool: read one file from the frozen, provenance-tagged corpus.

The allow-list is ``knowledge/source-register.json`` -- the register
``src/ingestion/tag_provenance.py`` already produces as the frozen list of
every document collected into the corpus. A model may only ask for a
``source_path`` that appears there (the same value it would already have
seen in retrieved evidence), and the file is read from where the register
says it actually lives, ``knowledge/corpus/<source_path>``. No second
allow-list (e.g. crawling the working tree with ``git ls-files``) is built
here; the register is the single source of truth for what's readable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping

from orchestrator import ToolRisk

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTER_PATH = REPO_ROOT / "knowledge" / "source-register.json"
DEFAULT_CORPUS_DIR = REPO_ROOT / "knowledge" / "corpus"

_VALID_STATUSES = frozenset({"ok", "path_not_allowed", "not_found"})


class ReadFileTool:
    """Read-only tool satisfying orchestrator.tool_dispatcher's Tool Protocol."""

    name = "read_file"
    risk = ToolRisk.READ_ONLY

    def __init__(
        self,
        *,
        register_path: Path | str = DEFAULT_REGISTER_PATH,
        corpus_dir: Path | str = DEFAULT_CORPUS_DIR,
        allowed_roles: Iterable[str] = ("developer",),
    ) -> None:
        self.corpus_dir = Path(corpus_dir)
        self.allowed_roles: Collection[str] = tuple(allowed_roles)
        self._allowed_paths = _load_allowed_paths(Path(register_path))

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Require a non-empty string ``path``; nothing else is accepted."""

        if not isinstance(arguments, Mapping) or set(arguments) != {"path"}:
            raise ValueError("read_file takes exactly one argument: 'path'.")

        path = arguments["path"]
        if not isinstance(path, str) or not path.strip():
            raise ValueError("'path' must be a non-empty string.")

        return {"path": path}

    def run(
        self,
        arguments: Mapping[str, Any],
        context: Any,
    ) -> Mapping[str, Any]:
        """Return the file's content, or why it could not be returned.

        path_not_allowed and not_found are reported as distinct, structured
        outcomes rather than raised -- both are ordinary results of a
        request, not tool failures, so they go through validate_output like
        any other successful dispatch.
        """

        path = arguments["path"]
        if path not in self._allowed_paths:
            return {"status": "path_not_allowed", "path": path}

        corpus_root = self.corpus_dir.resolve()
        file_path = (self.corpus_dir / path).resolve()
        if corpus_root not in file_path.parents:
            return {"status": "path_not_allowed", "path": path}
        if not file_path.is_file():
            return {"status": "not_found", "path": path}

        content = file_path.read_text(encoding="utf-8")
        return {"status": "ok", "path": path, "content": content}

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        status = output.get("status")
        if status not in _VALID_STATUSES:
            raise ValueError(f"read_file returned an unknown status: {status!r}.")
        if "path" not in output:
            raise ValueError("read_file output must include 'path'.")
        if status == "ok" and not isinstance(output.get("content"), str):
            raise ValueError("read_file output with status='ok' must include 'content'.")

        result = {"status": output["status"], "path": output["path"]}
        if status == "ok":
            result["content"] = output["content"]
        return result


def _load_allowed_paths(register_path: Path) -> frozenset[str]:
    payload = json.loads(register_path.read_text(encoding="utf-8"))
    return frozenset(entry["source_path"] for entry in payload["documents"])
