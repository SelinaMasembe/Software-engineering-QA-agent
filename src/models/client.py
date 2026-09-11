"""Provider-neutral model contract, errors, and chat-completions adapter."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import certifi
import ssl


class ModelIntegrationError(Exception):
    """Base class for errors safe to show to an application user."""


class IntegrationInputError(ModelIntegrationError):
    """Raised when the application supplies invalid integration input."""


class ModelConfigurationError(ModelIntegrationError):
    """Raised when required model-client configuration is invalid."""


class ModelAuthenticationError(ModelIntegrationError):
    """Raised when the provider rejects the configured credentials."""


class ModelRateLimitError(ModelIntegrationError):
    """Raised when the provider rejects a request because of a quota limit."""


class ModelTimeoutError(ModelIntegrationError):
    """Raised when the provider does not respond within the configured time."""


class ModelProviderError(ModelIntegrationError):
    """Raised when the provider returns an unusable response or service error."""


class ModelResponseError(ModelIntegrationError):
    """Raised when model output cannot be parsed or validated."""


@dataclass(frozen=True)
class TokenUsage:
    """Token counts reported by a provider, when available."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ModelCallResult:
    """Normalized result returned by every model-provider adapter."""

    raw_text: str
    model: str
    latency_ms: int
    usage: TokenUsage = field(default_factory=TokenUsage)
    request_id: str | None = None


class ModelClient(Protocol):
    """Interface implemented by model-provider adapters."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_content: str,
    ) -> ModelCallResult:
        """Return one model response for the supplied prompt and evidence."""


class ChatCompletionsClient:
    """Call a configured OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        temperature: float = 0.0,
        max_tokens: int = 1_200,
        json_mode: bool = True,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url.strip()
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        self.extra_headers = dict(extra_headers or {})
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        if not self.endpoint_url:
            raise ModelConfigurationError("Model endpoint URL is required.")
        if not self.api_key:
            raise ModelConfigurationError("Model API key is required.")
        if not self.model:
            raise ModelConfigurationError("Model name is required.")
        if self.timeout_seconds <= 0:
            raise ModelConfigurationError("Model timeout must be greater than zero.")
        if self.max_tokens <= 0:
            raise ModelConfigurationError(
                "Maximum output tokens must be greater than zero."
            )

    def generate(
        self,
        *,
        system_prompt: str,
        user_content: str,
    ) -> ModelCallResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self.extra_headers,
        }
        request = Request(
            self.endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        ssl_context = ssl.create_default_context(cafile=certifi.where())
        started = perf_counter()

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
                context=ssl_context,
            ) as response:
                response_body = response.read().decode("utf-8")
                request_id = _read_request_id(response)
        except HTTPError as exc:
            self._raise_for_http_error(exc)
        except (TimeoutError, socket.timeout) as exc:
            raise ModelTimeoutError(
                f"The model provider did not respond within "
                f"{self.timeout_seconds:g} seconds."
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ModelTimeoutError(
                    f"The model provider did not respond within "
                    f"{self.timeout_seconds:g} seconds."
                ) from exc
            raise ModelProviderError("The model provider could not be reached.") from exc
        except OSError as exc:
            raise ModelProviderError("The model provider request failed.") from exc

        latency_ms = round((perf_counter() - started) * 1_000)
        return self._normalize_response(response_body, latency_ms, request_id)

    @staticmethod
    def _raise_for_http_error(exc: HTTPError) -> None:
        if exc.code in {401, 403}:
            raise ModelAuthenticationError(
                "The model provider rejected the configured credentials."
            ) from exc
        if exc.code == 429:
            raise ModelRateLimitError(
                "The model provider rejected the request because of a rate or quota "
                "limit."
            ) from exc
        if exc.code in {408, 504}:
            raise ModelTimeoutError("The model provider timed out.") from exc
        raise ModelProviderError(
            f"The model provider returned HTTP status {exc.code}."
        ) from exc

    def _normalize_response(
        self,
        response_body: str,
        latency_ms: int,
        request_id: str | None,
    ) -> ModelCallResult:
        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                "The model provider returned a non-JSON API response."
            ) from exc

        try:
            message = payload["choices"][0]["message"]
            content = _extract_text_content(message["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError(
                "The model provider response did not contain assistant text."
            ) from exc

        if not content.strip():
            raise ModelProviderError("The model provider returned an empty response.")

        usage_payload = payload.get("usage") or {}
        usage = TokenUsage(
            input_tokens=_optional_int(usage_payload.get("prompt_tokens")),
            output_tokens=_optional_int(usage_payload.get("completion_tokens")),
            total_tokens=_optional_int(usage_payload.get("total_tokens")),
        )
        returned_model = payload.get("model")
        return ModelCallResult(
            raw_text=content,
            model=returned_model if isinstance(returned_model, str) else self.model,
            latency_ms=latency_ms,
            usage=usage,
            request_id=request_id,
        )


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [
            item["text"]
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        return "".join(text_parts)
    raise TypeError("Unsupported assistant content type")


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read_request_id(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    request_id = headers.get("x-request-id") or headers.get("request-id")
    return request_id if isinstance(request_id, str) else None
