"""Tests for scripts/check_sensitive.py.

Fake secrets are built by concatenation so this file does not trip the hook itself.
"""
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_sensitive.py"
spec = importlib.util.spec_from_file_location("check_sensitive", SCRIPT)
cs = importlib.util.module_from_spec(spec)
sys.modules["check_sensitive"] = cs  # dataclasses needs the module registered
spec.loader.exec_module(cs)

FAKE_GOOGLE_KEY = "AIza" + "Sy" + "B" * 33
ENV_EXAMPLE = """\
# Google AI Studio OpenAI-compatible endpoint
MODEL_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
MODEL_NAME=gemini-3.5-flash-lite
# Replace locally. Never commit a real API key.
MODEL_API_KEY=replace-with-your-google-ai-studio-key
MODEL_TIMEOUT_SECONDS=30
MODEL_MAX_TOKENS=1200
MODEL_JSON_MODE=true
"""


def scan(path, text):
    return cs.scan_file(path, text.encode())


def rules(findings):
    return {f.rule for f in findings}


# File names
def test_env_example_is_clean():
    assert scan(".env.example", ENV_EXAMPLE) == []


def test_real_env_file_is_blocked_by_name():
    assert any("never committed" in f.rule for f in scan(".env", ENV_EXAMPLE))


def test_env_variants_and_keys_blocked():
    for name in [".env.local", "prod.env", "server.pem", "id_rsa", "run.log", "service-account-qa.json"]:
        assert cs.check_filename(name) is not None, name


def test_templates_allowed():
    for name in [".env.example", ".env.sample", ".env.template"]:
        assert cs.check_filename(name) is None, name


# Leaked values
def test_real_key_in_env_example_is_blocked():
    text = ENV_EXAMPLE.replace("replace-with-your-google-ai-studio-key", FAKE_GOOGLE_KEY)
    found = rules(scan(".env.example", text))
    assert "Google API key" in found
    assert any(r.startswith("hardcoded value") for r in found)


def test_google_key_in_python_blocked():
    assert "Google API key" in rules(scan("agent/llm.py", f'KEY = "{FAKE_GOOGLE_KEY}"\n'))


def test_hardcoded_password_with_type_hint():
    line = "db_" + 'password: str = "' + "hunter2" + "Hunter2" + '"\n'
    assert scan("agent/config.py", line)


def test_private_key_block():
    text = "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n"
    assert "private key block" in rules(scan("fixtures/key.txt", text))


def test_password_in_url():
    text = "DATABASE_URL=postgres://qa:" + "S3cretPass" + "@db:5432/app\n"
    assert "password in URL" in rules(scan("config.yaml", text))


def test_uganda_phone_and_card():
    text = "contact +256" + "700123456\ncard 4111 1111 " + "1111 1111\n"
    found = rules(scan("fixtures/users.csv", text))
    assert "Uganda phone number" in found
    assert "payment card number" in found


def test_bearer_jwt():
    jwt = "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + "." + "c" * 12
    assert "JSON Web Token" in rules(scan("notes/issue_draft.md", f"Authorization: Bearer {jwt}\n"))


# Things that must stay quiet
def test_env_lookup_in_code_is_fine():
    code = 'api_key = os.environ["MODEL_API_KEY"]\ntoken = settings.token\nmax_tokens = 1200\n'
    assert scan("agent/llm.py", code) == []


def test_prose_word_is_not_a_secret():
    assert scan("README.md", "Token: authentication is required.\n") == []


def test_pragma_suppresses():
    line = f'KEY = "{FAKE_GOOGLE_KEY}"  # ' + "pragma: allowlist " + "secret\n"
    assert scan("tests/fixtures.py", line) == []


def test_binary_file_skips_content():
    assert cs.scan_file("image.png", b"\x89PNG\0" + FAKE_GOOGLE_KEY.encode()) == []

def test_test_credentials_are_placeholders():
    assert scan("config.py", 'api_key = "test-key"\n') == []
    assert scan("config.py", 'api_key = "test-key-never-log"\n') == []