"""Application configuration for the QA Agent model integration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from models.client import (
    ChatCompletionsClient,
    ModelConfigurationError,
)


@dataclass(frozen=True)
class ModelSettings:
    """Validated settings required to construct the model client."""

    endpoint_url: str
    api_key: str
    model: str
    timeout_seconds: float = 30.0
    max_tokens: int = 1_200
    json_mode: bool = True


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ModelConfigurationError(
            f"Required environment variable {name} is missing."
        )
    return value


def _parse_positive_float(name: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ModelConfigurationError(
            f"Environment variable {name} must be a number."
        ) from exc

    if parsed <= 0:
        raise ModelConfigurationError(
            f"Environment variable {name} must be greater than zero."
        )
    return parsed


def _parse_positive_int(name: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ModelConfigurationError(
            f"Environment variable {name} must be an integer."
        ) from exc

    if parsed <= 0:
        raise ModelConfigurationError(
            f"Environment variable {name} must be greater than zero."
        )
    return parsed


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()

    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False

    raise ModelConfigurationError(
        f"Environment variable {name} must be true or false."
    )


def _validate_endpoint(endpoint_url: str) -> None:
    parsed = urlparse(endpoint_url)

    if parsed.scheme != "https" or not parsed.netloc:
        raise ModelConfigurationError(
            "MODEL_ENDPOINT must be a complete HTTPS URL."
        )


def load_model_settings() -> ModelSettings:
    """Load and validate model settings from environment variables."""

    endpoint_url = _required_environment("MODEL_ENDPOINT")
    _validate_endpoint(endpoint_url)

    api_key = _required_environment("MODEL_API_KEY")
    model = _required_environment("MODEL_NAME")

    timeout_seconds = _parse_positive_float(
        "MODEL_TIMEOUT_SECONDS",
        os.environ.get("MODEL_TIMEOUT_SECONDS", "30"),
    )
    max_tokens = _parse_positive_int(
        "MODEL_MAX_TOKENS",
        os.environ.get("MODEL_MAX_TOKENS", "1200"),
    )
    json_mode = _parse_bool(
        "MODEL_JSON_MODE",
        os.environ.get("MODEL_JSON_MODE", "true"),
    )

    return ModelSettings(
        endpoint_url=endpoint_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )


def build_model_client() -> ChatCompletionsClient:
    """Construct the configured provider client."""

    settings = load_model_settings()

    return ChatCompletionsClient(
        endpoint_url=settings.endpoint_url,
        api_key=settings.api_key,
        model=settings.model,
        timeout_seconds=settings.timeout_seconds,
        max_tokens=settings.max_tokens,
        json_mode=settings.json_mode,
    )