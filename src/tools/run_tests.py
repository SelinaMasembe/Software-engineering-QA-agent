"""The run_tests tool: validate a sandboxed test-execution request, then run
it through an injected SandboxExecutor.

``models.types`` reserves ``RejectionReason``, ``RejectedExecution``,
``TestOutcome``, ``TestResult``, and ``SandboxExecutionResult`` by name for
"whoever implements run_tests ... in Week 4" -- the same reserved-shape
pattern ``IssueDraft`` established for draft_issue -- so this tool reuses
them rather than inventing new ones.

This is the batch/session adapter ``src/sandbox/executor.py`` deliberately
left for this file to own: ``SandboxExecutor.execute(test_node_id)`` runs
one test and returns one ``TestResult``; ``run()`` here calls it once per
``test_node_id`` in the request and assembles the results into one
``SandboxExecutionResult`` carrying the real ``session_id``, attaching the
identity information the executor itself has no business inventing.

``SandboxExecutor`` is constructor-injected, the same dependency-injection
pattern ``SearchRepoTool`` uses for its ``RetrievalPipeline`` and
``DraftIssueTool`` uses for its ``DraftStore`` -- not instantiated inside
``run()``.

This is a REQUIRES_APPROVAL tool, so ``run()`` is only ever reached after
approval; orchestrator.router's ``except Exception`` around
``run()`` converts any exception it raises into a generic
``DispatchStatus.TOOL_ERROR`` / ``DispatchCode.EXECUTION_FAILED`` without
leaking its text to the caller -- confirmed by reading ``dispatch()``
directly, not assumed.

Which test_node_ids are valid is checked in ``validate_arguments`` against
the constructor-injected manifest, before the approval gate is ever
consulted and long before ``run()`` sees them. ``run()`` should therefore
never see an ID the sandbox itself considers uncollectible. If it somehow
does -- the manifest and the real test suite have drifted out of sync --
that is a contradiction worth failing loudly on, not silently swallowing;
see ``ManifestDriftError`` below.
"""

from __future__ import annotations

from typing import Any, Collection, Iterable, Mapping

from models.types import RejectionReason, SandboxExecutionResult, TestOutcome, TestResult
from orchestrator import ToolRisk
from sandbox import SandboxExecutor

_UNKNOWN_ID_MARKER = f"[{RejectionReason.UNKNOWN_TEST_NODE_ID.value}]"


class ManifestDriftError(RuntimeError):
    """Raised when a test_node_id passed manifest validation in
    validate_arguments, but the sandbox itself could not collect it at
    run() time. This should never happen -- it means the injected manifest
    no longer matches the real test suite the sandbox executes against --
    and is deliberately raised rather than silently folded into an ordinary
    ERROR result, which would hide a manifest that has gone stale.
    """


class RunTestsTool:
    """Approval-gated tool satisfying orchestrator.router's Tool Protocol."""

    name = "run_tests"
    risk = ToolRisk.REQUIRES_APPROVAL

    def __init__(
        self,
        manifest: Collection[str],
        sandbox: SandboxExecutor,
        *,
        allowed_roles: Iterable[str] = ("developer",),
    ) -> None:
        self.manifest = frozenset(manifest)
        self.sandbox = sandbox
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
        """Run each test_node_id through the sandbox and assemble one
        SandboxExecutionResult for this session.

        manifest membership was already checked in validate_arguments, so
        every ID here is expected to be collectible; a result that still
        comes back tagged as unknown means the manifest and the real test
        suite have drifted, and that is raised as ManifestDriftError rather
        than silently accepted.
        """

        session_id = arguments["session_id"]
        test_node_ids = arguments["test_node_ids"]

        results: list[TestResult] = []
        for test_node_id in test_node_ids:
            result = self.sandbox.execute(test_node_id)
            if result.outcome is TestOutcome.ERROR and result.stderr.startswith(
                _UNKNOWN_ID_MARKER
            ):
                raise ManifestDriftError(
                    f"{test_node_id!r} passed manifest validation but the "
                    "sandbox could not collect it."
                )
            results.append(result)

        execution = SandboxExecutionResult(session_id=session_id, results=tuple(results))

        return {
            "session_id": execution.session_id,
            "results": [
                {
                    "test_id": result.test_id,
                    "outcome": result.outcome.value,
                    "duration_ms": result.duration_ms,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
                for result in execution.results
            ],
            "rejected": [
                {"test_id": rejection.test_id, "reason": rejection.reason.value}
                for rejection in execution.rejected
            ],
        }

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
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
