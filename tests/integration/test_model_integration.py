from __future__ import annotations

import io
import json
import socket
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from models.client import (
    ChatCompletionsClient,
    IntegrationInputError,
    ModelAuthenticationError,
    ModelCallResult,
    ModelProviderError,
    ModelResponseError,
    ModelTimeoutError,
    TokenUsage,
)
from rag.pipeline import ProposalInput, generate_test_proposals


VALID_OUTPUT = {
    "status": "success",
    "proposals": [
        {
            "title": "Reject an invalid password",
            "source_refs": ["REQ-AUTH-01", "login_service.py:6"],
            "confidence": "high",
        }
    ],
}


class FakeModelClient:
    def __init__(self, raw_text: str) -> None:
        self.raw_text = raw_text
        self.system_prompt: str | None = None
        self.user_content: str | None = None

    def generate(self, *, system_prompt: str, user_content: str) -> ModelCallResult:
        self.system_prompt = system_prompt
        self.user_content = user_content
        return ModelCallResult(
            raw_text=self.raw_text,
            model="fake-week2-model",
            latency_ms=12,
            usage=TokenUsage(input_tokens=30, output_tokens=20, total_tokens=50),
            request_id="request-123",
        )


class FakeHTTPResponse:
    def __init__(self, payload: dict, headers: dict[str, str] | None = None) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def make_input() -> ProposalInput:
    return ProposalInput(
        requirement_id="REQ-AUTH-01",
        requirement_text="Invalid credentials must be rejected.",
        source_path="login_service.py",
        source_text="def authenticate(username, password): return password == 'correct'",
    )


def make_client() -> ChatCompletionsClient:
    return ChatCompletionsClient(
        endpoint_url="https://provider.example/v1/chat/completions",
        api_key="test-key-never-log",
        model="week2-model",
        timeout_seconds=8,
    )


class PipelineTests(unittest.TestCase):
    def test_runs_model_and_returns_parsed_output_with_metadata(self) -> None:
        client = FakeModelClient(json.dumps(VALID_OUTPUT))

        result = generate_test_proposals(
            proposal_input=make_input(),
            system_prompt="Return structured test proposals as JSON.",
            prompt_version="v1.0",
            client=client,
        )

        self.assertEqual(result.output, VALID_OUTPUT)
        self.assertEqual(result.model, "fake-week2-model")
        self.assertEqual(result.prompt_version, "v1.0")
        self.assertEqual(result.request_id, "request-123")
        self.assertEqual(client.system_prompt, "Return structured test proposals as JSON.")
        sent_evidence = json.loads(client.user_content or "")
        self.assertEqual(sent_evidence["requirement"]["id"], "REQ-AUTH-01")
        self.assertEqual(sent_evidence["source"]["path"], "login_service.py")

    def test_accepts_member_one_domain_parser_without_owning_domain_models(self) -> None:
        client = FakeModelClient(json.dumps(VALID_OUTPUT))

        def member_one_parser(raw_text: str) -> tuple[str, int]:
            parsed = json.loads(raw_text)
            return parsed["status"], len(parsed["proposals"])

        result = generate_test_proposals(
            proposal_input=make_input(),
            system_prompt="Return JSON.",
            prompt_version="v1.0",
            client=client,
            response_parser=member_one_parser,
        )

        self.assertEqual(result.output, ("success", 1))

    def test_rejects_non_json_model_output(self) -> None:
        client = FakeModelClient("Here are several useful tests.")

        with self.assertRaisesRegex(ModelResponseError, "valid JSON"):
            generate_test_proposals(
                proposal_input=make_input(),
                system_prompt="Return JSON.",
                prompt_version="v1.0",
                client=client,
            )

    def test_rejects_json_array_instead_of_object(self) -> None:
        client = FakeModelClient("[]")

        with self.assertRaisesRegex(ModelResponseError, "JSON object"):
            generate_test_proposals(
                proposal_input=make_input(),
                system_prompt="Return JSON.",
                prompt_version="v1.0",
                client=client,
            )

    def test_rejects_empty_evidence_before_calling_provider(self) -> None:
        client = FakeModelClient(json.dumps(VALID_OUTPUT))

        with self.assertRaisesRegex(IntegrationInputError, "Requirement text"):
            generate_test_proposals(
                proposal_input=ProposalInput(
                    requirement_text=" ",
                    source_text="pass",
                    source_path="module.py",
                ),
                system_prompt="Return JSON.",
                prompt_version="v1.0",
                client=client,
            )

        self.assertIsNone(client.user_content)


class ChatCompletionsClientTests(unittest.TestCase):
    @patch("qa_agent.model_integration.urlopen")
    def test_normalizes_successful_provider_response(self, mocked_urlopen) -> None:
        model_output = {"status": "success", "proposals": []}
        mocked_urlopen.return_value = FakeHTTPResponse(
            {
                "model": "returned-model-version",
                "choices": [{"message": {"content": json.dumps(model_output)}}],
                "usage": {
                    "prompt_tokens": 19,
                    "completion_tokens": 7,
                    "total_tokens": 26,
                },
            },
            headers={"x-request-id": "provider-request-7"},
        )

        result = make_client().generate(
            system_prompt="Return JSON.",
            user_content='{"requirement":{},"source":{}}',
        )

        self.assertEqual(json.loads(result.raw_text), model_output)
        self.assertEqual(result.model, "returned-model-version")
        self.assertEqual(result.usage.total_tokens, 26)
        self.assertEqual(result.request_id, "provider-request-7")

        request = mocked_urlopen.call_args.args[0]
        sent_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent_body["model"], "week2-model")
        self.assertEqual(sent_body["response_format"], {"type": "json_object"})
        self.assertEqual(
            request.get_header("Authorization"), "Bearer test-key-never-log"
        )

    @patch("qa_agent.model_integration.urlopen", side_effect=socket.timeout())
    def test_translates_socket_timeout(self, _mocked_urlopen) -> None:
        with self.assertRaisesRegex(ModelTimeoutError, "8 seconds"):
            make_client().generate(system_prompt="Prompt", user_content="Evidence")

    @patch("qa_agent.model_integration.urlopen")
    def test_translates_authentication_failure_without_leaking_key(
        self, mocked_urlopen
    ) -> None:
        mocked_urlopen.side_effect = HTTPError(
            "https://provider.example/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"unauthorized"}'),
        )

        with self.assertRaises(ModelAuthenticationError) as context:
            make_client().generate(system_prompt="Prompt", user_content="Evidence")

        self.assertNotIn("test-key-never-log", str(context.exception))

    @patch("qa_agent.model_integration.urlopen")
    def test_rejects_provider_response_without_assistant_text(
        self, mocked_urlopen
    ) -> None:
        mocked_urlopen.return_value = FakeHTTPResponse({"choices": []})

        with self.assertRaisesRegex(ModelProviderError, "assistant text"):
            make_client().generate(system_prompt="Prompt", user_content="Evidence")


if __name__ == "__main__":
    unittest.main()
