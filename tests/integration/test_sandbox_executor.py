from __future__ import annotations

import os
import unittest

from models.types import TestOutcome
from sandbox.executor import REPO_ROOT, SandboxExecutor

FIXTURE_FILE = "tests/fixtures/sandbox/sample_cases.py"


class SandboxExecutorRealSubprocessTests(unittest.TestCase):
    """Runs the real executor against real pytest subprocesses -- no
    mocked subprocess calls, per the point of this test file.
    """

    def setUp(self) -> None:
        self.executor = SandboxExecutor()

    def test_a_passing_test_reports_pass(self) -> None:
        result = self.executor.execute(f"{FIXTURE_FILE}::test_addition_passes")

        self.assertIs(result.outcome, TestOutcome.PASS)
        self.assertEqual(result.test_id, f"{FIXTURE_FILE}::test_addition_passes")
        self.assertGreaterEqual(result.duration_ms, 0)
        self.assertIn("1 passed", result.stdout)

    def test_a_failing_test_reports_fail(self) -> None:
        result = self.executor.execute(f"{FIXTURE_FILE}::test_subtraction_deliberately_fails")

        self.assertIs(result.outcome, TestOutcome.FAIL)
        self.assertIn("1 failed", result.stdout)

    def test_an_unknown_test_node_id_is_distinct_from_a_real_failure(self) -> None:
        result = self.executor.execute(f"{FIXTURE_FILE}::test_this_does_not_exist")

        self.assertIs(result.outcome, TestOutcome.ERROR)
        self.assertIn("unknown_test_node_id", result.stderr)
        # A real failure's stderr must never carry this marker, so the two
        # are programmatically distinguishable, not just human-readable.
        real_failure = self.executor.execute(
            f"{FIXTURE_FILE}::test_subtraction_deliberately_fails"
        )
        self.assertNotIn("unknown_test_node_id", real_failure.stderr)

    def test_a_nonexistent_file_is_also_reported_as_unknown_test_node_id(self) -> None:
        result = self.executor.execute("tests/fixtures/sandbox/does_not_exist.py::test_x")

        self.assertIs(result.outcome, TestOutcome.ERROR)
        self.assertIn("unknown_test_node_id", result.stderr)

    def test_a_hanging_test_times_out_as_error_not_an_unhandled_raise(self) -> None:
        executor = SandboxExecutor(timeout_seconds=1.0)

        result = executor.execute(f"{FIXTURE_FILE}::test_sleeps_past_any_reasonable_timeout")

        self.assertIs(result.outcome, TestOutcome.ERROR)
        self.assertIn("timeout", result.stderr.lower())
        # subprocess.run enforces the timeout itself; this should complete
        # near the 1s limit, not the fixture's full 5s sleep.
        self.assertLess(result.duration_ms, 4000)

    def test_the_parent_environment_is_not_inherited_by_the_subprocess(self) -> None:
        sentinel = "leaked-from-parent-process-should-never-appear"
        os.environ["FAKE_SECRET_TOKEN"] = sentinel
        self.addCleanup(os.environ.pop, "FAKE_SECRET_TOKEN", None)

        result = self.executor.execute(
            f"{FIXTURE_FILE}::test_fake_secret_token_is_not_in_the_environment"
        )

        # The fixture test itself asserts the var isn't in os.environ inside
        # the subprocess -- if the stripping failed, this would be FAIL/ERROR.
        self.assertIs(result.outcome, TestOutcome.PASS)
        self.assertNotIn(sentinel, result.stdout)
        self.assertNotIn(sentinel, result.stderr)

    def test_environment_actually_used_is_a_strict_allowlist(self) -> None:
        os.environ["FAKE_SECRET_TOKEN"] = "should-not-be-forwarded"
        self.addCleanup(os.environ.pop, "FAKE_SECRET_TOKEN", None)

        env = self.executor._build_environment()

        self.assertNotIn("FAKE_SECRET_TOKEN", env)
        self.assertIn("PYTHONPATH", env)
        self.assertEqual(env["PYTHONPATH"], str(REPO_ROOT / "src"))
        allowed = {"PATH", "LANG", "SYSTEMROOT", "COMSPEC", "APPDATA", "PYTHONPATH"}
        self.assertTrue(set(env).issubset(allowed))

    def test_no_shell_is_used_and_arguments_are_not_string_interpolated(self) -> None:
        # A shell-interpreted injection payload as the "test id" must be
        # treated as one literal (bogus) argument, never executed.
        payload = "tests/fixtures/sandbox/sample_cases.py; echo INJECTED"

        result = self.executor.execute(payload)

        self.assertIs(result.outcome, TestOutcome.ERROR)
        self.assertIn("unknown_test_node_id", result.stderr)
        self.assertNotIn("INJECTED", result.stdout)


class SandboxExecutorConfigurationTests(unittest.TestCase):
    def test_non_positive_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SandboxExecutor(timeout_seconds=0)

    def test_blank_test_node_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SandboxExecutor().execute("   ")


if __name__ == "__main__":
    unittest.main()
