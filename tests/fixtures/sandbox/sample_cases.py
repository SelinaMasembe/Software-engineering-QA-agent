"""Throwaway pytest cases for exercising SandboxExecutor against a real
subprocess. Deliberately named so the main suite's `pytest tests/` run
does NOT auto-discover it (pytest's default collection glob is
test_*.py/*_test.py) -- these are only ever run by explicit node id, from
tests/integration/test_sandbox_executor.py. One of these is meant to fail
and one is meant to hang; that is the point of this fixture.
"""

import os
import time


def test_addition_passes():
    assert 1 + 1 == 2


def test_subtraction_deliberately_fails():
    assert 1 - 1 == 1


def test_sleeps_past_any_reasonable_timeout():
    time.sleep(5)


def test_fake_secret_token_is_not_in_the_environment():
    assert "FAKE_SECRET_TOKEN" not in os.environ
