from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from models.client import ModelConfigurationError
from config.loader import build_model_client, load_model_settings


class ModelConfigurationTests(unittest.TestCase):
    def test_loads_model_settings_from_environment(self) -> None:
        environment = {
            "MODEL_ENDPOINT": "https://provider.example/v1/chat/completions",
            "MODEL_API_KEY": "test-key",
            "MODEL_NAME": "test-model",
            "MODEL_TIMEOUT_SECONDS": "8",
            "MODEL_MAX_TOKENS": "900",
            "MODEL_JSON_MODE": "false",
        }

        with patch.dict(os.environ, environment, clear=True):
            settings = load_model_settings()

        self.assertEqual(settings.endpoint_url, environment["MODEL_ENDPOINT"])
        self.assertEqual(settings.api_key, "test-key")
        self.assertEqual(settings.model, "test-model")
        self.assertEqual(settings.timeout_seconds, 8.0)
        self.assertEqual(settings.max_tokens, 900)
        self.assertFalse(settings.json_mode)

    def test_rejects_missing_api_key(self) -> None:
        environment = {
            "MODEL_ENDPOINT": "https://provider.example/v1/chat/completions",
            "MODEL_NAME": "test-model",
        }

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                ModelConfigurationError,
                "MODEL_API_KEY",
            ):
                load_model_settings()

    def test_rejects_non_https_endpoint(self) -> None:
        environment = {
            "MODEL_ENDPOINT": "http://provider.example/v1/chat/completions",
            "MODEL_API_KEY": "test-key",
            "MODEL_NAME": "test-model",
        }

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                ModelConfigurationError,
                "HTTPS",
            ):
                load_model_settings()

    def test_rejects_invalid_boolean(self) -> None:
        environment = {
            "MODEL_ENDPOINT": "https://provider.example/v1/chat/completions",
            "MODEL_API_KEY": "test-key",
            "MODEL_NAME": "test-model",
            "MODEL_JSON_MODE": "maybe",
        }

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                ModelConfigurationError,
                "true or false",
            ):
                load_model_settings()

    def test_builds_client_without_exposing_api_key_in_errors(self) -> None:
        environment = {
            "MODEL_ENDPOINT": "https://provider.example/v1/chat/completions",
            "MODEL_API_KEY": "test-key-never-log",
            "MODEL_NAME": "test-model",
        }

        with patch.dict(os.environ, environment, clear=True):
            client = build_model_client()

        self.assertEqual(client.model, "test-model")
        self.assertEqual(client.api_key, "test-key-never-log")


if __name__ == "__main__":
    unittest.main()