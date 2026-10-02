"""Runs one pytest test node in a subprocess with a stripped environment and
a hard timeout.

This is new, unowned infrastructure -- it is not any team member's Week 4
deliverable. It exists to satisfy the contract
``src/tools/run_tests.py``'s ``SandboxNotImplementedError`` has been
documenting:

    def execute(
        self, *, session_id: str, test_node_ids: Sequence[str],
    ) -> models.types.SandboxExecutionResult: ...

That is a *batch*, session-aware contract: it takes many test_node_ids for
one session and returns a ``SandboxExecutionResult`` whose ``rejected``
entries are ``RejectedExecution`` objects requiring a ``session_id`` and a
``logged_at`` timestamp this executor has no business inventing. This file
deliberately builds one level below that: ``SandboxExecutor.execute(test_node_id)``
runs exactly one test and returns one ``TestResult`` (from
``models.types``, reused as-is -- no parallel shape). Wiring this into
``RunTestsTool`` is handled by ``src/tools/run_tests.py``: its ``run()``
method calls this once per test ID and assembles the final
``SandboxExecutionResult`` with the session identity it owns.

Security posture (Security and Risk Register R3/R4/R5/R7, confirmed against
the register before writing this):
  - R3 (no general shell access): the subprocess argument list is built
    directly, never a shell string -- ``shell=False``, always, and nothing
    beyond "run this exact pytest node id" is representable.
  - R4 (no credential exposure via environment): the subprocess never
    inherits the parent's environment. Only an explicit allowlist is
    passed; ``PYTHONPATH`` is computed here, never inherited.
  - R5 (environment isolation): every invocation is scoped to this one
    subprocess, given a controlled working directory and environment.
  - R7 (resource limits regardless of test content): a hard wall-clock
    timeout is enforced; a runaway test is killed, not left to hang.

What this class explicitly does NOT do: true filesystem or network
isolation. A test still has this process's file permissions and network
access. Only environment-variable exposure (R4) and runaway wall-clock
duration (R7) are mitigated here. Real filesystem/network sandboxing would
require containers or an OS-level sandbox, which is out of scope for this
pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter
from typing import BinaryIO

from models.types import RejectionReason, TestOutcome, TestResult

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"

DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_CAPTURE_BYTES = 64_000

# Deliberately small. PYTHONPATH is computed by this class, never inherited;
# everything else needed to launch Python correctly (and nothing else) goes
# here. SYSTEMROOT/COMSPEC are required for Python's own subprocess/socket
# machinery to start correctly on Windows -- omitting them does not improve
# isolation, it just breaks process creation on this platform. APPDATA is
# required too whenever a dependency (pytest, here) is installed to the
# per-user site-packages directory rather than a venv: CPython's site
# module resolves that location from %APPDATA%\Python\PythonXY\site-packages
# on Windows, and without it the interpreter cannot even find pytest to
# import it (confirmed: stripping it produces "No module named pytest",
# not a security improvement, just a broken subprocess). None of these are
# credential-bearing values -- they are filesystem paths and locale/console
# settings a process needs to start at all.
_ALLOWED_ENV_VARS = ("PATH", "LANG", "SYSTEMROOT", "COMSPEC", "APPDATA")

# pytest exit codes: 0 all passed, 1 some failed, 2 interrupted,
# 3 internal error, 4 usage error, 5 no tests collected. 4 and 5 are what
# an unknown/mistyped test_node_id actually produces (confirmed empirically:
# both a nonexistent file and a nonexistent test in a real file return 4).
_NOT_COLLECTIBLE_RETURN_CODES = frozenset({4, 5})


class SandboxExecutor:
    """Runs exactly one pytest node ID per call, never the full suite.

    Prevents credential leakage via environment stripping (R4) and runaway
    processes via a wall-clock timeout (R7). Does NOT provide true
    filesystem or network sandboxing -- a test still runs with this
    process's file and network access; only what it can read from its
    environment and how long it may run are constrained.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        repo_root: Path | str = REPO_ROOT,
        python_executable: str = sys.executable,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        self.timeout_seconds = timeout_seconds
        self.repo_root = Path(repo_root)
        self.python_executable = python_executable

    def execute(self, test_node_id: str) -> TestResult:
        """Run one pytest node ID in a subprocess and return its TestResult.

        A not-collectible ID (typo, missing file) is distinguished from a
        real test error: its stderr is prefixed with the exact
        ``RejectionReason.UNKNOWN_TEST_NODE_ID`` value, reusing the
        existing enum's canonical string rather than inventing new wording,
        so a caller can tell the two apart programmatically. It is still
        returned as a TestResult (outcome=ERROR) rather than a
        RejectedExecution, because RejectedExecution requires a session_id
        and a logged_at timestamp this single-test, session-unaware
        executor does not have -- attaching those, and reclassifying this
        into SandboxExecutionResult.rejected, belongs to the batch-level
        caller described in this module's docstring.
        """

        if not isinstance(test_node_id, str) or not test_node_id.strip():
            raise ValueError("test_node_id must be a non-empty string.")

        command = [self.python_executable, "-m", "pytest", test_node_id]
        env = self._build_environment()

        started = perf_counter()
        with (
            tempfile.TemporaryFile() as stdout_file,
            tempfile.TemporaryFile() as stderr_file,
        ):
            process = subprocess.Popen(
                command,
                cwd=self.repo_root,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
            )
            try:
                process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                duration_ms = _elapsed_ms(started)
                stdout = _read_capped_text(stdout_file)
                stderr = _read_capped_text(stderr_file)
                return TestResult(
                    test_id=test_node_id,
                    outcome=TestOutcome.ERROR,
                    duration_ms=duration_ms,
                    stdout=stdout,
                    stderr=(
                        f"{stderr}\n[timeout] exceeded {self.timeout_seconds:g}s "
                        "wall-clock limit; process was killed."
                    ).strip(),
                )

            duration_ms = _elapsed_ms(started)
            stdout = _read_capped_text(stdout_file)
            stderr = _read_capped_text(stderr_file)

            if process.returncode in _NOT_COLLECTIBLE_RETURN_CODES:
                stderr = (
                    f"[{RejectionReason.UNKNOWN_TEST_NODE_ID.value}] {stderr}"
                ).strip()
                return TestResult(
                    test_id=test_node_id,
                    outcome=TestOutcome.ERROR,
                    duration_ms=duration_ms,
                    stdout=stdout,
                    stderr=stderr,
                )

            if process.returncode == 0:
                outcome = TestOutcome.PASS
            elif process.returncode == 1:
                outcome = TestOutcome.FAIL
            else:
                outcome = TestOutcome.ERROR

            return TestResult(
                test_id=test_node_id,
                outcome=outcome,
                duration_ms=duration_ms,
                stdout=stdout,
                stderr=stderr,
            )

    def _build_environment(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for name in _ALLOWED_ENV_VARS:
            value = os.environ.get(name)
            if value is not None:
                env[name] = value
        env.setdefault("LANG", "C.UTF-8")
        env["PYTHONPATH"] = str(SRC_DIR)
        return env


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1_000)


def _read_capped_text(stream: BinaryIO) -> str:
    stream.seek(0)
    output = stream.read(_MAX_CAPTURE_BYTES + 1)
    truncated = len(output) > _MAX_CAPTURE_BYTES
    text = output[:_MAX_CAPTURE_BYTES].decode("utf-8", errors="replace")
    if truncated:
        return f"{text}\n[output truncated to {_MAX_CAPTURE_BYTES} bytes]".strip()
    return text
