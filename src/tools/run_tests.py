"""The run_tests tool: validate a sandboxed test-execution request, but do
not execute it -- no sandbox executor exists anywhere in this repo yet.

Confirmed fresh: grepping "sandbox"/"Executor"/"execute_test" across src/
and scripts/ turns up only the forward-declared vocabulary in
models/types.py, no real execution logic. That module's own docstring
reserves ``RejectionReason``, ``RejectedExecution``, ``TestOutcome``,
``TestResult``, and ``SandboxExecutionResult`` by name for "whoever
implements run_tests ... in Week 4" -- the same reserved-shape pattern
``IssueDraft`` established for draft_issue -- so this tool reuses them
rather than inventing new ones.

``run()`` therefore raises SandboxNotImplementedError instead of faking an
execution result; a made-up pass/fail would misrepresent a capability that
does not exist. This is a REQUIRES_APPROVAL tool, so ``run()`` is only ever
reached after approval; orchestrator.tool_dispatcher's ``except Exception``
around ``run()`` converts any exception it raises, this one included, into
a generic ``DispatchStatus.TOOL_ERROR`` / ``DispatchCode.EXECUTION_FAILED``
without leaking its text to the caller -- confirmed by reading
``dispatch()`` directly, not assumed.

Which test_node_ids are even valid is a separate question from whether they
can be executed (``RejectionReason`` already keeps UNKNOWN_TEST_NODE_ID and
OUTSIDE_SANDBOX distinct). No frozen manifest of valid IDs exists in the
repo either. ``pytest --collect-only`` can enumerate them mechanically, but
shelling out to pytest at runtime is foreign to every other manifest in
this codebase (``knowledge/source-register.json``, ``IndexManifest``),
which are frozen, versioned artifacts, not something recomputed by
invoking a subprocess. So the manifest is constructor-injected here, the
same dependency-injection pattern ``SearchRepoTool`` uses for its
``RetrievalPipeline`` -- how it gets produced is left to whoever assembles
this tool, not decided in this file.
"""

from __future__ import annotations

from typing import Any, Collection, Iterable, Mapping

from models.types import RejectionReason, TestOutcome
from orchestrator import ToolRisk


class SandboxNotImplementedError(NotImplementedError):
    """Raised by RunTestsTool.run(): no sandbox executor exists yet.

    Whoever builds one must implement an object with this method:

        def execute(
            self, *, session_id: str, test_node_ids: Sequence[str],
        ) -> models.types.SandboxExecutionResult: ...

    ``SandboxExecutionResult`` (src/models/types.py) must be returned with:
      - ``results: tuple[TestResult, ...]`` -- one per test actually run,
        each carrying ``test_id``, ``outcome`` (a ``TestOutcome`` member:
        PASS/FAIL/ERROR), ``duration_ms``, ``stdout``, ``stderr``.
      - ``rejected: tuple[RejectedExecution, ...]`` -- anything requested
        but refused inside the sandbox (e.g. ``RejectionReason.
        OUTSIDE_SANDBOX`` or ``SECRET_ACCESS_ATTEMPT``), logged rather than
        silently dropped.

    RunTestsTool would then take that executor via its constructor, the
    same way SearchRepoTool takes a RetrievalPipeline, and ``run()`` would
    call ``executor.execute(session_id=..., test_node_ids=...)`` instead of
    raising this.
    """


class RunTestsTool:
    """Approval-gated tool satisfying orchestrator.tool_dispatcher's Tool Protocol.

    validate_arguments/validate_output are fully implemented and tested;
    run() intentionally is not -- see SandboxNotImplementedError.
    """

    name = "run_tests"
    risk = ToolRisk.REQUIRES_APPROVAL

    def __init__(
        self,
        manifest: Collection[str],
        *,
        allowed_roles: Iterable[str] = ("developer",),
    ) -> None:
        self.manifest = frozenset(manifest)
        self.allowed_roles: Collection[str] = tuple(allowed_roles)

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Require session_id and a non-empty list of manifest-known test_node_ids."""

        if not isinstance(arguments, Mapping):
            raise ValueError("run_tests arguments must be an object.")

        allowed_keys = {"session_id", "test_node_ids"}
        missing = allowed_keys - set(arguments)
        if missing:
            raise ValueError(f"run_tests is missing required argument(s): {sorted(missing)}.")
        unknown = set(arguments) - allowed_keys
        if unknown:
            raise ValueError(f"run_tests received unknown argument(s): {sorted(unknown)}.")

        session_id = arguments["session_id"]
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("'session_id' must be a non-empty string.")

        test_node_ids = arguments["test_node_ids"]
        if not isinstance(test_node_ids, (list, tuple)) or not test_node_ids:
            raise ValueError("'test_node_ids' must be a non-empty list.")

        normalized_ids: list[str] = []
        for test_id in test_node_ids:
            if not isinstance(test_id, str) or not test_id.strip():
                raise ValueError("Every entry in 'test_node_ids' must be a non-empty string.")
            if test_id not in self.manifest:
                raise ValueError(
                    f"{test_id!r} is not a known test_node_id "
                    f"({RejectionReason.UNKNOWN_TEST_NODE_ID.value})."
                )
            normalized_ids.append(test_id)

        return {"session_id": session_id, "test_node_ids": tuple(normalized_ids)}

    def run(
        self,
        arguments: Mapping[str, Any],
        context: Any,
    ) -> Mapping[str, Any]:
        """Never completes -- see SandboxNotImplementedError."""

        raise SandboxNotImplementedError(
            "run_tests has no sandbox executor to call. See "
            "tools.run_tests.SandboxNotImplementedError for the interface "
            "whoever builds one must implement."
        )

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        """Written and tested even though run() cannot produce input for it yet."""

        session_id = output.get("session_id")
        results = output.get("results")
        rejected = output.get("rejected", [])

        if not isinstance(session_id, str) or not session_id:
            raise ValueError("run_tests output must include a non-empty 'session_id'.")
        if not isinstance(results, list):
            raise ValueError("run_tests output must include a list of 'results'.")
        if not isinstance(rejected, list):
            raise ValueError("run_tests output 'rejected' must be a list.")

        return {
            "session_id": session_id,
            "results": [_validate_result_entry(entry) for entry in results],
            "rejected": [_validate_rejected_entry(entry) for entry in rejected],
        }


def _validate_result_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, Mapping):
        raise ValueError("Every run_tests result must be an object.")

    test_id = entry.get("test_id")
    outcome = entry.get("outcome")
    duration_ms = entry.get("duration_ms")
    stdout = entry.get("stdout")
    stderr = entry.get("stderr")

    if not isinstance(test_id, str) or not test_id:
        raise ValueError("Every run_tests result must include a non-empty 'test_id'.")
    try:
        TestOutcome(outcome)
    except ValueError as exc:
        raise ValueError(f"Unknown test outcome: {outcome!r}.") from exc
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0:
        raise ValueError("'duration_ms' must be a non-negative integer.")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise ValueError("'stdout' and 'stderr' must be strings.")

    return {
        "test_id": test_id,
        "outcome": outcome,
        "duration_ms": duration_ms,
        "stdout": stdout,
        "stderr": stderr,
    }


def _validate_rejected_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, Mapping):
        raise ValueError("Every run_tests rejection must be an object.")

    test_id = entry.get("test_id")
    reason = entry.get("reason")

    if not isinstance(test_id, str) or not test_id:
        raise ValueError("Every run_tests rejection must include a non-empty 'test_id'.")
    try:
        RejectionReason(reason)
    except ValueError as exc:
        raise ValueError(f"Unknown rejection reason: {reason!r}.") from exc

    return {"test_id": test_id, "reason": reason}
