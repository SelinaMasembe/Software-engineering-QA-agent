"""Load and validate application configuration from environment variables.
    This file loads configuration for an AI model from environment variables, checks that the values are valid, stores them in a ModelSettings object, and uses those settings to create a ChatCompletionsClient.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

from models.client import ChatCompletionsClient, ModelConfigurationError

#: Upper bounds that catch a typo (an extra zero) before it reaches the client.
MAX_TIMEOUT_SECONDS = 600.0
MAX_TOKENS_LIMIT = 65_536


@dataclass(frozen=True)
class ModelSettings:
    """Validated settings required to construct the model client."""

    endpoint_url: str
    # repr=False: printing or logging the settings must never show the key.
    api_key: str = field(repr=False)
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


def _optional_environment(name: str, default: str) -> str:
    """Return the variable's value, or ``default`` when it is unset or blank."""

    value = os.environ.get(name, "").strip()
    return value or default


def _parse_positive_float(name: str, value: str, *, maximum: float) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ModelConfigurationError(
            f"Environment variable {name} must be a number."
        ) from exc

    # nan and inf pass a plain "> 0" check and then crash the HTTP client.
    if not math.isfinite(parsed) or parsed <= 0:
        raise ModelConfigurationError(
            f"Environment variable {name} must be a finite number greater than zero."
        )
    if parsed > maximum:
        raise ModelConfigurationError(
            f"Environment variable {name} must be at most {maximum:g}."
        )

    return parsed


def _parse_positive_int(name: str, value: str, *, maximum: int) -> int:
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
    if parsed > maximum:
        raise ModelConfigurationError(
            f"Environment variable {name} must be at most {maximum}."
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
    if any(char.isspace() or ord(char) < 32 for char in endpoint_url):
        raise ModelConfigurationError(
            "MODEL_ENDPOINT must not contain spaces or control characters."
        )
    # Credentials belong in MODEL_API_KEY, never inside the URL, where they
    # would end up in logs and error messages.
    if parsed.username is not None or parsed.password is not None:
        raise ModelConfigurationError(
            "MODEL_ENDPOINT must not contain a username or password."
        )


def load_model_settings() -> ModelSettings:
    """Load and validate model settings from the process environment."""

    endpoint_url = _required_environment("MODEL_ENDPOINT")
    _validate_endpoint(endpoint_url)

    api_key = _required_environment("MODEL_API_KEY")
    model = _required_environment("MODEL_NAME")

    timeout_seconds = _parse_positive_float(
        "MODEL_TIMEOUT_SECONDS",
        _optional_environment("MODEL_TIMEOUT_SECONDS", "30"),
        maximum=MAX_TIMEOUT_SECONDS,
    )

    max_tokens = _parse_positive_int(
        "MODEL_MAX_TOKENS",
        _optional_environment("MODEL_MAX_TOKENS", "1200"),
        maximum=MAX_TOKENS_LIMIT,
    )

    json_mode = _parse_bool(
        "MODEL_JSON_MODE",
        _optional_environment("MODEL_JSON_MODE", "true"),
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
    """Build a configured model client from validated environment settings."""

    settings = load_model_settings()

    return ChatCompletionsClient(
        endpoint_url=settings.endpoint_url,
        api_key=settings.api_key,
        model=settings.model,
        timeout_seconds=settings.timeout_seconds,
        max_tokens=settings.max_tokens,
        json_mode=settings.json_mode,
    )