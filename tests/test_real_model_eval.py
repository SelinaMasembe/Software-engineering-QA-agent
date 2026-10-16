"""Tests for scripts/real_model_eval.py. Stub clients only: no network, no real key.

The key tests use a made-up value, set only inside the test. The one test
that exercises the real ChatCompletionsClient replaces its ``urlopen`` with a
fake, so no request leaves the process.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from models.client import ModelCallResult, ModelProviderError, ModelRateLimitError, TokenUsage

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "real_model_eval.py"
spec = importlib.util.spec_from_file_location("real_model_eval", SCRIPT)
rme = importlib.util.module_from_spec(spec)
# Registered first: dataclasses look the module up while the file executes.
sys.modules["real_model_eval"] = rme
spec.loader.exec_module(rme)

FAKE_KEY = "test-only-fake-key-7f3a9c1e5b2d4086"  # pragma: allowlist secret


def valid_reply(source_path: str, *, action: str = "propose_test", evidence=True, extra: str = "") -> str:
    return json.dumps({
        "action": action,
        "arguments": {"title": "t" + extra},
        "rationale": "r" + extra,
        "evidence": [{"source_path": source_path, "note": "n"}] if evidence else [],
        "confidence": "high",
    })


class ScriptedClient:
    """A fake live client. ``script`` is a list of replies or exceptions, used in order."""

    model = "fake-model"
    temperature = 0.0
    max_tokens = 64

    def __init__(self, script, api_key: str = FAKE_KEY) -> None:
        self.api_key = api_key
        self.script = list(script)
        self.calls = 0

    def generate(self, *, system_prompt: str, user_content: str) -> ModelCallResult:
        self.calls += 1
        item = self.script.pop(0) if self.script else self.script_default(user_content)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(user_content)
        return ModelCallResult(item, "fake-model-returned", 5, TokenUsage(10, 3, 13))

    @staticmethod
    def script_default(user_content: str) -> str:
        path = user_content.split('source_path="')[2].split('"')[0]
        return valid_reply(path)


def all_output_text(out_dir: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(out_dir.rglob("*")) if p.is_file())


class RunMixin:
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.sleeps: list[float] = []
        self.addCleanup(self._tmp.cleanup)

    def run_eval(self, client=None, *, live=True, versions=("v1.3",), runs=1, max_calls=80, cases=None):
        def factory():
            return client

        with mock.patch("builtins.print"):
            return rme.run_evaluation(
                versions=list(versions), runs=runs, live=live, out_root=self.root,
                max_calls=max_calls, client_factory=factory, sleep=self.sleeps.append,
                cases=cases,
            )


class OutputFileTests(RunMixin, unittest.TestCase):
    def test_one_json_per_call_plus_csv_and_summary(self) -> None:
        result = self.run_eval(ScriptedClient([]))

        calls = sorted((result.out_dir / "calls").glob("*.json"))
        self.assertEqual(len(calls), 10)
        self.assertTrue((result.out_dir / "summary.csv").is_file())
        self.assertTrue((result.out_dir / "summary.json").is_file())
        lines = (result.out_dir / "summary.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 11)
        self.assertEqual(lines[0].split(","), list(rme.CSV_FIELDS))

        record = json.loads(calls[0].read_text(encoding="utf-8"))
        for key in ("case_id", "prompt_version", "run_index", "model_requested", "temperature",
                    "max_tokens", "latency_ms", "usage", "raw_model_text", "parse_result",
                    "citations_valid", "criteria", "exception"):
            self.assertIn(key, record)
        self.assertEqual(record["criteria"]["tool_selection"], {"result": rme.NOT_APPLICABLE})
        self.assertEqual(record["criteria"]["stop_reason"], {"result": rme.NOT_APPLICABLE})

    def test_context_uses_forward_slash_paths_and_wrapped_evidence(self) -> None:
        context = rme.build_case_context(rme.load_cases()[0])

        self.assertEqual(context.text.count("<evidence "), 2)
        self.assertEqual(context.text.count("</evidence>"), 2)
        self.assertEqual(context.allowed_source_paths,
                         frozenset({"requirements/REQ-QA-01.md", "pricing/discount.py"}))
        self.assertNotIn("\\", "".join(context.allowed_source_paths))

    def test_summary_counts_no_action_and_empty_evidence_and_bad_citations(self) -> None:
        script = [
            lambda u: valid_reply("x", action="no_action", evidence=False),
            lambda u: valid_reply("REQ-QA-02"),
            "not json",
        ]
        result = self.run_eval(ScriptedClient(script))
        summary = json.loads((result.out_dir / "summary.json").read_text(encoding="utf-8"))
        v = summary["per_version"]["v1.3"]

        self.assertEqual(v["calls_recorded"], 10)
        self.assertEqual(v["no_action_returned"], 1)
        self.assertEqual(v["no_action_with_empty_evidence"], 1)
        self.assertEqual(v["cites_requirement_id_as_path"], 1)
        self.assertEqual(v["valid_parse"], 9)
        self.assertEqual(v["invalid_citations"], 2)
        self.assertEqual(v["outcomes"]["NOT_SCORED"], 1)
        self.assertEqual(sum(v["outcomes"].values()), 10)


class KeyNeverWrittenTests(RunMixin, unittest.TestCase):
    def test_the_fake_key_appears_in_no_output_file(self) -> None:
        result = self.run_eval(ScriptedClient([ModelProviderError("boom")]))

        self.assertNotIn(FAKE_KEY, all_output_text(result.out_dir))

    def test_a_reply_that_echoes_the_key_is_redacted(self) -> None:
        result = self.run_eval(ScriptedClient([lambda u: valid_reply("pricing/discount.py", extra=FAKE_KEY)]))

        text = all_output_text(result.out_dir)
        self.assertNotIn(FAKE_KEY, text)
        self.assertIn("[REDACTED]", text)

    def test_the_real_client_path_with_a_fake_transport_writes_no_key_or_header(self) -> None:
        sent: list = []

        class FakeResponse:
            headers: dict = {}

            def __init__(self, body: str) -> None:
                self.body = body

            def read(self) -> bytes:
                return self.body.encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *exc) -> None:
                return None

        def fake_urlopen(request, timeout, context):
            sent.append(request)
            user = json.loads(request.data)["messages"][1]["content"]
            path = user.split('source_path="')[2].split('"')[0]
            body = {"choices": [{"message": {"content": valid_reply(path)}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    "model": "fake"}
            return FakeResponse(json.dumps(body))

        env = {"MODEL_ENDPOINT": "https://example.invalid/v1/chat/completions",
               "MODEL_API_KEY": FAKE_KEY, "MODEL_NAME": "fake-model"}
        with mock.patch.dict(os.environ, env), mock.patch("models.client.urlopen", fake_urlopen), \
                mock.patch("builtins.print"):
            result = rme.run_evaluation(versions=["v1.3"], runs=1, live=True, out_root=self.root,
                                        max_calls=80, sleep=self.sleeps.append)

        self.assertEqual(len(sent), 10)
        self.assertEqual(sent[0].get_header("Authorization"), f"Bearer {FAKE_KEY}")
        text = all_output_text(result.out_dir)
        self.assertNotIn(FAKE_KEY, text)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("Bearer", text)
        self.assertEqual(result.records[0].status, "ok")


class StopTests(RunMixin, unittest.TestCase):
    def test_max_calls_stops_the_run(self) -> None:
        client = ScriptedClient([])
        result = self.run_eval(client, versions=("v1.1", "v1.3"), runs=3, max_calls=4)

        self.assertEqual(client.calls, 4)
        self.assertEqual(len(result.records), 4)
        self.assertIn("--max-calls 4", result.stopped_early)
        summary = json.loads((result.out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["http_attempts"], 4)

    def test_three_consecutive_failures_stop_the_run(self) -> None:
        client = ScriptedClient([ModelProviderError("down")] * 10)
        result = self.run_eval(client)

        self.assertEqual(client.calls, 3)
        self.assertEqual(len(result.records), 3)
        self.assertIn("3 consecutive failures", result.stopped_early)
        self.assertTrue(all(r.status == "call_failed" for r in result.records))

    def test_a_success_resets_the_failure_count(self) -> None:
        bad = ModelProviderError("down")
        client = ScriptedClient([bad, bad, None, bad, bad])
        client.script[2] = ScriptedClient.script_default
        result = self.run_eval(client)

        self.assertIsNone(result.stopped_early)
        self.assertEqual(len(result.records), 10)

    def test_parse_failures_count_as_failures(self) -> None:
        result = self.run_eval(ScriptedClient(["{", "[]", "not json"]))

        self.assertIn("3 consecutive failures", result.stopped_early)
        self.assertEqual([r.status for r in result.records], ["parse_failed"] * 3)


class RateLimitTests(RunMixin, unittest.TestCase):
    def test_a_429_is_retried_and_the_retry_is_recorded(self) -> None:
        limit = ModelRateLimitError("quota")
        result = self.run_eval(ScriptedClient([limit, limit]))

        first = result.records[0]
        self.assertEqual(first.status, "ok")
        self.assertEqual(first.retries_after_429, 2)
        self.assertEqual(first.attempts, 3)
        self.assertEqual(self.sleeps, list(rme.RATE_LIMIT_BACKOFF_SECONDS))

    def test_a_429_is_retried_at_most_twice(self) -> None:
        limit = ModelRateLimitError("quota")
        client = ScriptedClient([limit, limit, limit])
        result = self.run_eval(client)

        first = result.records[0]
        self.assertEqual(first.status, "call_failed")
        self.assertEqual(first.attempts, 3)
        self.assertEqual(first.retries_after_429, 2)
        self.assertIn("ModelRateLimitError", first.exception)
        self.assertEqual(len(self.sleeps), 2)

    def test_retries_count_toward_max_calls(self) -> None:
        limit = ModelRateLimitError("quota")
        client = ScriptedClient([limit, limit])
        result = self.run_eval(client, max_calls=2)

        self.assertEqual(client.calls, 2)
        self.assertEqual(result.records[0].status, "call_failed")


class FakeClock:
    """Time only moves when something sleeps or a fake call takes time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class TimedClient(ScriptedClient):
    """Each call takes ``duration`` seconds of fake time; start times are kept."""

    def __init__(self, clock: FakeClock, duration: float, script=()) -> None:
        super().__init__(script)
        self.clock = clock
        self.duration = duration
        self.starts: list[float] = []

    def generate(self, *, system_prompt: str, user_content: str) -> ModelCallResult:
        self.starts.append(self.clock())
        self.clock.now += self.duration
        return super().generate(system_prompt=system_prompt, user_content=user_content)


class MinIntervalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.clock = FakeClock()

    def run_eval(self, client, *, interval, live=True, max_calls=80):
        with mock.patch("builtins.print"):
            return rme.run_evaluation(
                versions=["v1.3"], runs=1, live=live, out_root=self.root, max_calls=max_calls,
                client_factory=lambda: client, sleep=self.clock.sleep, clock=self.clock,
                min_interval_seconds=interval,
            )

    def test_starts_are_spaced_by_at_least_the_interval_and_waits_are_recorded(self) -> None:
        client = TimedClient(self.clock, duration=3.0)
        result = self.run_eval(client, interval=10.0)

        gaps = [b - a for a, b in zip(client.starts, client.starts[1:])]
        self.assertEqual(len(client.starts), 10)
        self.assertTrue(all(gap >= 10.0 for gap in gaps), gaps)
        self.assertEqual(result.records[0].interval_waits_seconds, [0.0])
        for record in result.records[1:]:
            self.assertEqual(record.interval_waits_seconds, [7.0])
        saved = json.loads(next((result.out_dir / "calls").glob("normal_clear_defect*")).read_text())
        self.assertEqual(saved["interval_waits_seconds"], [0.0])
        summary = json.loads((result.out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["min_interval_seconds"], 10.0)
        self.assertEqual(summary["interval_wait_total_seconds"], 63.0)

    def test_no_wait_when_a_call_already_took_longer_than_the_interval(self) -> None:
        client = TimedClient(self.clock, duration=12.0)
        result = self.run_eval(client, interval=10.0)

        self.assertEqual(self.clock.sleeps, [])
        self.assertTrue(all(r.interval_waits_seconds == [0.0] for r in result.records))

    def test_the_default_of_zero_never_waits(self) -> None:
        client = TimedClient(self.clock, duration=0.5)
        result = self.run_eval(client, interval=0.0)

        self.assertEqual(self.clock.sleeps, [])
        self.assertTrue(all(r.interval_waits_seconds == [0.0] for r in result.records))

    def test_a_429_backoff_counts_toward_the_interval_and_retries_are_paced(self) -> None:
        client = TimedClient(self.clock, duration=1.0, script=[ModelRateLimitError("quota")])
        result = self.run_eval(client, interval=10.0)

        first = result.records[0]
        self.assertEqual(first.attempts, 2)
        # The 20 s backoff already exceeds the 10 s interval: no extra wait.
        self.assertEqual(first.interval_waits_seconds, [0.0, 0.0])
        self.assertEqual(self.clock.sleeps[0], rme.RATE_LIMIT_BACKOFF_SECONDS[0])
        self.assertEqual(result.records[1].interval_waits_seconds, [9.0])

    def test_short_backoff_still_honours_a_longer_interval(self) -> None:
        client = TimedClient(self.clock, duration=1.0, script=[ModelRateLimitError("quota")])
        with mock.patch.object(rme, "RATE_LIMIT_BACKOFF_SECONDS", (2.0, 2.0)):
            result = self.run_eval(client, interval=10.0)

        self.assertEqual(result.records[0].interval_waits_seconds, [0.0, 7.0])
        self.assertGreaterEqual(client.starts[1] - client.starts[0], 10.0)

    def test_max_calls_still_counts_and_a_refused_call_is_not_waited_for(self) -> None:
        client = TimedClient(self.clock, duration=1.0)
        result = self.run_eval(client, interval=5.0, max_calls=3)

        self.assertEqual(client.calls, 3)
        self.assertIn("--max-calls 3", result.stopped_early)
        self.assertEqual(self.clock.sleeps, [4.0, 4.0])

    def test_three_consecutive_failures_still_stop_the_run(self) -> None:
        client = TimedClient(self.clock, duration=1.0, script=[ModelProviderError("down")] * 5)
        result = self.run_eval(client, interval=5.0)

        self.assertEqual(client.calls, 3)
        self.assertIn("3 consecutive failures", result.stopped_early)
        self.assertEqual([r.interval_waits_seconds for r in result.records], [[0.0], [4.0], [4.0]])

    def test_the_key_is_still_never_written(self) -> None:
        client = TimedClient(self.clock, duration=1.0)
        result = self.run_eval(client, interval=5.0)

        self.assertNotIn(FAKE_KEY, all_output_text(result.out_dir))

    def test_a_dry_run_never_waits_and_never_builds_a_client(self) -> None:
        def no_client():
            raise AssertionError("the dry run constructed a model client")

        with mock.patch("models.client.urlopen", side_effect=AssertionError("network")), \
                mock.patch("builtins.print"):
            result = rme.run_evaluation(
                versions=["v1.3"], runs=1, live=False, out_root=self.root, max_calls=80,
                client_factory=no_client, sleep=self.clock.sleep, clock=self.clock,
                min_interval_seconds=30.0,
            )

        self.assertEqual(self.clock.sleeps, [])
        self.assertTrue(all(r.interval_waits_seconds == [] for r in result.records))

    def test_negative_interval_is_rejected(self) -> None:
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            rme.main(["--min-interval-seconds", "-1"])
        with self.assertRaises(ValueError):
            self.run_eval(ScriptedClient([]), interval=-1.0)


class DryRunTests(RunMixin, unittest.TestCase):
    def test_the_dry_run_never_constructs_a_client_or_opens_a_connection(self) -> None:
        def no_client():
            raise AssertionError("the dry run constructed a model client")

        with mock.patch("config.build_model_client", side_effect=AssertionError("constructed")), \
                mock.patch("models.client.urlopen", side_effect=AssertionError("network")), \
                mock.patch.dict(os.environ, {"MODEL_API_KEY": FAKE_KEY}), \
                mock.patch("builtins.print"):
            result = rme.run_evaluation(versions=["v1.1", "v1.3"], runs=1, live=False,
                                        out_root=self.root, max_calls=80, client_factory=no_client)

        self.assertEqual(len(result.records), 20)
        self.assertTrue(all(r.model_returned == rme.STUB_MODEL for r in result.records))
        self.assertTrue(result.out_dir.name.endswith("_dryrun"))
        self.assertNotIn(FAKE_KEY, all_output_text(result.out_dir))

    def test_the_cli_dry_run_writes_files(self) -> None:
        with mock.patch("builtins.print"):
            code = rme.main(["--prompt-version", "v1.3", "--runs", "1", "--out", str(self.root)])

        self.assertEqual(code, 0)
        (run_dir,) = self.root.iterdir()
        self.assertEqual(len(list((run_dir / "calls").glob("*.json"))), 10)


if __name__ == "__main__":
    unittest.main()
