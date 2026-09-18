#!/usr/bin/env python3
"""Pre-commit guard. Blocks staged files that look like they hold secrets or personal data.

Usage:
    python scripts/check_sensitive.py            # scan staged files (git hook)
    python scripts/check_sensitive.py --all      # scan every tracked file (CI)
    python scripts/check_sensitive.py FILE ...   # scan given files (pre-commit framework)

False positives:
    - Add `pragma: allowlist secret` to the offending line.
    - Or add a glob to .sensitive-scan-ignore (one per line, # for comments).

Exit code 1 blocks the commit.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

IGNORE_FILE = ".sensitive-scan-ignore"
PRAGMA = "pragma: allowlist secret"
MAX_BYTES = 2_000_000

# Never commit these, whatever they contain.
BLOCKED_NAMES = [
    ".env", ".env.*", "*.env",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".netrc", ".pypirc",
    "credentials.json", "client_secret*.json", "service-account*.json", "*-sa-key.json",
    "*.sqlite", "*.sqlite3", "*.db",
    "*.log",  # sandbox runs and model calls can log keys and prompts
]
# Templates are allowed. Their values are still scanned.
TEMPLATE_NAMES = [".env.example", ".env.sample", ".env.template", "*.env.example"]

# Files where `KEY=value` without quotes is normal.
CONFIG_SUFFIXES = {".env", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml",
                   ".json", ".properties"}
CONFIG_NAMES = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
# Prose. Needs stronger evidence before blocking.
PROSE_SUFFIXES = {".md", ".txt", ".rst"}


# Findings
@dataclass(frozen=True)
class Finding:
    path: str
    line: int  # 0 = whole file
    rule: str
    snippet: str = ""

    def __str__(self) -> str:
        loc = self.path if self.line == 0 else f"{self.path}:{self.line}"
        tail = f"  [{self.snippet}]" if self.snippet else ""
        return f"  {loc}  {self.rule}{tail}"


def redact(value: str) -> str:
    value = value.strip()
    return value[:4] + "***" if len(value) > 4 else "***"


# Validators
PLACEHOLDER_RE = re.compile(
    r"""(?ix)^(?:
        | x+ | \*+ | \.+ | -+
        | none | null | nil | true | false | undefined
        | changeme | change[-_]?me | todo | tbd | redacted | dummy | fake
        | test(?:[-_](?:key|token|secret|password))(?:[-_].*)?
        | example | sample | placeholder | secret | password | token
        | <.*> | \{\{.*\}\} | \$\{.*\} | \$[A-Z_][A-Z0-9_]* | %\(.*\)s
        | your[-_ ].* | replace[-_ ].* | enter[-_ ].* | insert[-_ ].*
        | .*example.* | .*placeholder.* | .*replace[-_ ]?with.* | .*changeme.*
    )$"""
)


def is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_RE.match(value.strip()))


def char_classes(value: str) -> int:
    return sum([
        any(c.islower() for c in value),
        any(c.isupper() for c in value),
        any(c.isdigit() for c in value),
        any(not c.isalnum() for c in value),
    ])


def luhn_ok(raw: str) -> bool:
    digits = [int(c) for c in raw if c.isdigit()]
    if len(set(digits)) < 2:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def nin_ok(raw: str) -> bool:
    return sum(c.isdigit() for c in raw) >= 5


def not_placeholder(raw: str) -> bool:
    return not is_placeholder(raw)


# Content rules
Validator = Optional[Callable[[str], bool]]

PATTERN_RULES: list[tuple[str, re.Pattern[str], Validator, int]] = [
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"), None, 0),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), None, 0),
    ("Google OAuth token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}"), None, 0),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), None, 0),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"), None, 0),
    ("sk- style API key (OpenAI/Anthropic)", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"), None, 0),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), None, 0),
    ("Stripe live key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{20,}"), None, 0),
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), None, 0),
    ("password in URL", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:([^\s:/@]+)@", re.I), not_placeholder, 1),
    ("Uganda phone number", re.compile(r"(?<![\d+])(?:\+256|256|0)7\d{8}(?!\d)"), None, 0),
    ("Uganda National ID (NIN)", re.compile(r"\bC[MF]\d{2}[A-Z0-9]{10}\b"), nin_ok, 0),
    ("payment card number", re.compile(
        r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6011)(?:[ -]?\d{4}){2}[ -]?\d{3,4}\b"), luhn_ok, 0),
]

KEY_NAME = (
    r"(?<![A-Za-z0-9_])"
    r"(?P<name>[A-Za-z0-9_.\-]*?(?:api[_-]?key|access[_-]?key|private[_-]?key|"
    r"client[_-]?secret|secret(?:[_-]?key)?|auth[_-]?token|token|password|passwd|pwd))"
)
# Code: only flag string literals. `api_key = os.environ["X"]` is fine.
CODE_ASSIGN_RE = re.compile(
    KEY_NAME + r"""["']?(?:\s*:\s*[\w\[\]|., ]+?)?\s*[:=]\s*(?P<q>["'])(?P<value>[^"'\n]*)(?P=q)""",
    re.I,
)
# Config and prose: unquoted values count too.
LOOSE_ASSIGN_RE = re.compile(
    KEY_NAME + r"""["']?\s*[:=]\s*["']?(?P<value>[^\s"'#,;]*)""",
    re.I,
)


def file_mode(path: str) -> str:
    p = PurePosixPath(path)
    if p.name.startswith(".env") or p.suffix in CONFIG_SUFFIXES or p.name in CONFIG_NAMES:
        return "config"
    if p.suffix in PROSE_SUFFIXES:
        return "prose"
    return "code"


def scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    mode = file_mode(path)
    assign_re = CODE_ASSIGN_RE if mode == "code" else LOOSE_ASSIGN_RE

    for lineno, line in enumerate(text.splitlines(), start=1):
        if PRAGMA in line:
            continue

        for rule, regex, validator, group in PATTERN_RULES:
            for m in regex.finditer(line):
                hit = m.group(group)
                if validator and not validator(hit):
                    continue
                findings.append(Finding(path, lineno, rule, redact(hit)))

        for m in assign_re.finditer(line):
            value = m.group("value").strip()
            if len(value) < 8 or is_placeholder(value):
                continue
            if mode == "prose" and char_classes(value) < 2:
                continue
            findings.append(Finding(path, lineno, f"hardcoded value for '{m.group('name')}'", redact(value)))

    return findings


def check_filename(path: str) -> Optional[Finding]:
    name = PurePosixPath(path).name
    if any(fnmatch.fnmatch(name, pat) for pat in TEMPLATE_NAMES):
        return None
    for pat in BLOCKED_NAMES:
        if fnmatch.fnmatch(name, pat):
            return Finding(path, 0, f"file type is never committed ({pat})")
    return None


# Git plumbing
def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def repo_root() -> Path:
    return Path(git("rev-parse", "--show-toplevel").decode().strip())


def staged_files() -> list[str]:
    out = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    return [p for p in out.decode().split("\0") if p]


def tracked_files() -> list[str]:
    return [p for p in git("ls-files", "-z").decode().split("\0") if p]


def load_ignores(root: Path) -> list[str]:
    f = root / IGNORE_FILE
    if not f.is_file():
        return []
    lines = (l.strip() for l in f.read_text(encoding="utf-8").splitlines())
    return [l for l in lines if l and not l.startswith("#")]


def is_ignored(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) or PurePosixPath(path).match(pat) for pat in patterns)


def read_blob(path: str, root: Path, from_index: bool) -> Optional[bytes]:
    try:
        data = git("show", f":{path}") if from_index else (root / path).read_bytes()
    except (subprocess.CalledProcessError, OSError):
        return None
    return data


def scan_file(path: str, data: bytes) -> list[Finding]:
    findings: list[Finding] = []
    blocked = check_filename(path)
    if blocked:
        findings.append(blocked)
    if len(data) > MAX_BYTES or b"\0" in data[:8000]:
        return findings  # binary or huge, name check only
    findings.extend(scan_text(path, data.decode("utf-8", errors="replace")))
    return findings


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="files to scan (default: staged files)")
    parser.add_argument("--all", action="store_true", help="scan every tracked file")
    args = parser.parse_args(argv)

    root = repo_root()
    ignores = load_ignores(root)

    if args.files:
        paths, from_index = args.files, False
    elif args.all:
        paths, from_index = tracked_files(), False
    else:
        paths, from_index = staged_files(), True

    findings: list[Finding] = []
    for path in paths:
        path = PurePosixPath(Path(path)).as_posix()
        if path == IGNORE_FILE or is_ignored(path, ignores):
            continue
        data = read_blob(path, root, from_index)
        if data is not None:
            findings.extend(scan_file(path, data))

    if not findings:
        return 0

    print("\nCommit blocked. Possible secrets or personal data found:\n", file=sys.stderr)
    for f in findings:
        print(f, file=sys.stderr)
    print(
        "\nFix it:"
        "\n  1. Remove the value. Load it from the environment instead."
        "\n  2. Unstage the file: git restore --staged <file>"
        "\n  3. If a real key was exposed anywhere, rotate it now."
        f"\nFalse positive? Add '{PRAGMA}' to the line, or a glob to {IGNORE_FILE}.\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())