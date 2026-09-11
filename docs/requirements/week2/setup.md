# Development Setup Guide

This guide explains how to install, configure, test, and run the Software-Engineering QA Agent locally.

## 1. Clone and enter the repository

```bash
git clone <repository-url>
cd Software-engineering-QA-agent
```

## 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On macOS or Linux, use:

```bash
source .venv/bin/activate
```

## 3. Install dependencies

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

The current external dependency is `certifi`, used for verified HTTPS connections from Python.

## 4. Configure environment variables

Create a local environment file:

```bash
cp .env.example .env
```

Set the provider endpoint, available model ID, and local API key in `.env`.

Load the variables:

```bash
set -a
source .env
set +a
```

To confirm configuration without printing the key:

```bash
python3 - <<'PY'
import os

required = [
    "MODEL_ENDPOINT",
    "MODEL_NAME",
    "MODEL_API_KEY",
    "MODEL_TIMEOUT_SECONDS",
    "MODEL_MAX_TOKENS",
    "MODEL_JSON_MODE",
]

for name in required:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing environment variable: {name}")
    print(f"{name}={'configured' if name == 'MODEL_API_KEY' else value}")

print("Environment configuration is available.")
PY
```

## 5. Run offline tests

Run configuration tests:

```bash
PYTHONPATH=src python3 -m unittest tests.test_config -v
```

Run model integration tests:

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_model_integration -v
```

Run all offline tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

These tests use mocks or scripted responses. They do not require a live API key.

## 6. Run the live smoke test

```bash
PYTHONPATH=src python3 scripts/member2_model_smoke.py \
  --prompt-file docs/prompts/propose_action/v1.0.md \
  --prompt-version v1.0 \
  --requirement-id REQ-AUTH-01 \
  --requirement-file tests/fixtures/member2/login_requirement.txt \
  --source-file tests/fixtures/member2/login_service.py
```

The smoke test sends one real request and prints sanitized evidence. It does not create or execute test files.

## 7. Troubleshooting

- `MODEL_API_KEY is missing`: run `set -a; source .env; set +a`.
- SSL certificate failure: activate `.venv` and reinstall `requirements.txt`.
- HTTP 401 or 403: replace or verify the API key.
- HTTP 404: verify the exact model ID available to the API key.
- HTTP 429: wait for the rate limit to clear.
- HTTP 503: retry later because the provider may be temporarily unavailable.
- Invalid JSON: verify the model and prompt support structured JSON output.

Never disable SSL verification to bypass a certificate error.

## 8. Secret handling

- `.env` is ignored by Git.
- `.env.example` contains placeholders only.
- Never commit, screenshot, or paste a real API key.
- Revoke and replace any exposed key.
- Do not use production secrets or production data.

## 9. Evidence collection

For a successful live run, record only sanitized values:

- Model ID
- Prompt version
- Latency
- Token usage
- Parsed output
- Test command without the API key

Do not record the API key, full authorization headers, or sensitive source data.