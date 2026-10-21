"""Redact credential-shaped strings before content reaches the model (risk R4).

R4 says ingested content is scanned for credential-shaped strings before it
reaches the model. ``build_context`` calls ``redact_credentials`` on every
chunk it shows: each match is replaced with ``[REDACTED:credential]`` and a
``CredentialFlag`` records the rule and the span (offsets into the ORIGINAL
chunk text). The matched value itself is never stored anywhere.

Pure and deterministic: no model call, no file I/O, no clock, no network.

Where the patterns come from. ``scripts/check_sensitive.py`` is the commit-time
scanner. It lives under ``scripts/``, which is not an importable package from
``src/``, so the credential rules below are COPIED from it, not imported.
tests/test_credential_scan.py loads that script and fails if a copied pattern
drifts from its source. Its phone, national-ID and payment-card rules are not
copied: they are personal data, not credentials, and are out of scope here.

Added here, not in the commit scanner:
    CR-BEARER  an HTTP ``Bearer`` token.
    CR-ASSIGN  ``api_key=``, ``secret=``, ``token=`` or ``password=`` style
               assignments (in code, quoted literals only, as in the commit
               scanner) with a value of 16 or more characters that is not a
               placeholder (``your_api_key_here``, ``replace-with-...``,
               ``<token>``, ``${VAR}`` and the rest of the commit scanner's
               placeholder list).

Known limits (asserted in tests): a secret with no recognisable format and no
``key=`` label, a value shorter than 16 characters, and an encoded secret
(base64 of a key) are NOT detected. Format rules have no placeholder check,
exactly like the commit scanner, so a documented example key, such as the
access key ID AWS publishes in its documentation, is redacted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REDACTION = "[REDACTED:credential]"
CATEGORY = "credential"
MIN_ASSIGNED_VALUE = 16

# --- Copied verbatim from scripts/check_sensitive.py (kept in sync by a test) ---
COPIED_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # (rule id here, rule name in check_sensitive.py, pattern)
    ("CR-PRIVATE-KEY", "private key block", r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    ("CR-GOOGLE-KEY", "Google API key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("CR-GOOGLE-OAUTH", "Google OAuth token", r"\bya29\.[0-9A-Za-z_\-]{20,}"),
    ("CR-AWS-KEY", "AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("CR-GITHUB", "GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"),
    ("CR-SK-KEY", "sk- style API key (OpenAI/Anthropic)", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    ("CR-SLACK", "Slack token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    ("CR-STRIPE", "Stripe live key", r"\b[rs]k_live_[0-9A-Za-z]{20,}"),
    ("CR-JWT", "JSON Web Token", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
)
COPIED_URL_PASSWORD = r"\b(?<![a-z0-9+.\-])[a-z][a-z0-9+.\-]*://[^\s:/@]+:([^\s:/@]+)@"
COPIED_KEY_NAME = (
    r"(?<![A-Za-z0-9_.\-])"
    r"(?P<name>[A-Za-z0-9_.\-]*?(?:api[_-]?key|access[_-]?key|private[_-]?key|"
    r"client[_-]?secret|secret(?:[_-]?key)?|auth[_-]?token|token|password|passwd|pwd))"
)
# Code: only a quoted string literal counts. ``api_key = os.environ["X"]`` is fine.
COPIED_CODE_ASSIGN_SUFFIX = r"""["']?(?:\s*:\s*[\w\[\]|., ]+?)?\s*[:=]\s*(?P<q>["'])(?P<value>[^"'\n]*)(?P=q)"""
# Config and prose: unquoted values count too.
COPIED_LOOSE_ASSIGN_SUFFIX = r"""["']?\s*[:=]\s*["']?(?P<value>[^\s"'#,;]*)"""
COPIED_PLACEHOLDER = r"""(?ix)^(?:
        | x+ | \*+ | \.+ | -+
        | none | null | nil | true | false | undefined
        | changeme | change[-_]?me | todo | tbd | redacted | dummy | fake
        | test(?:[-_](?:key|token|secret|password))(?:[-_].*)?
        | example | sample | placeholder | secret | password | token
        | <.*> | \{\{.*\}\} | \$\{.*\} | \$[A-Z_][A-Z0-9_]* | %\(.*\)s
        | your[-_ ].* | replace[-_ ].* | enter[-_ ].* | insert[-_ ].*
        | .*example.* | .*placeholder.* | .*replace[-_ ]?with.* | .*changeme.*
    )$"""
# --- end of copied patterns ---

_PLACEHOLDER = re.compile(COPIED_PLACEHOLDER)
# Same split as the commit scanner: in code only quoted literals are values,
# so an expression like ``api_key = settings.api_key`` is not a credential.
_CODE_ASSIGN = re.compile(COPIED_KEY_NAME + COPIED_CODE_ASSIGN_SUFFIX, re.I)
_LOOSE_ASSIGN = re.compile(COPIED_KEY_NAME + COPIED_LOOSE_ASSIGN_SUFFIX, re.I)
_BEARER = re.compile(r"\bBearer\s+(?P<value>[A-Za-z0-9._~+/\-]{20,}=*)")
# A whole PEM private key, header to footer, when the footer is present. The
# body may not cross another "-----BEGIN ", so each scan stops at the next
# header and many headers with no footer stay linear.
_PEM_BLOCK = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----(?:(?!-----BEGIN ).)*?"
    r"-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----",
    re.DOTALL,
)

_FORMAT_RULES: tuple[tuple[str, "re.Pattern[str]"], ...] = tuple(
    (rule_id, re.compile(pattern)) for rule_id, _, pattern in COPIED_PATTERNS
) + (("CR-URL-PASSWORD", re.compile(COPIED_URL_PASSWORD, re.I)),)

RULE_IDS = tuple(rule_id for rule_id, _ in _FORMAT_RULES) + ("CR-BEARER", "CR-ASSIGN")


@dataclass(frozen=True)
class CredentialFlag:
    """Where a credential was found in the original text. Never the value."""

    rule_id: str
    start: int
    end: int
    category: str = CATEGORY

    def __post_init__(self) -> None:
        if self.rule_id not in RULE_IDS:
            raise ValueError(f"unknown rule_id {self.rule_id!r}.")
        if self.category != CATEGORY:
            raise ValueError(f"category must be {CATEGORY!r}.")
        for name in ("start", "end"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        if self.end <= self.start:
            raise ValueError("end must be after start.")


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER.match(value.strip()))


def find_credentials(text: str, *, code: bool = False) -> tuple[CredentialFlag, ...]:
    """Every credential-shaped span in ``text``, merged where spans overlap.

    ``code=True`` applies the commit scanner's code rule to assignments (a
    quoted literal only); otherwise its config-and-prose rule.
    """

    if not isinstance(text, str):
        raise TypeError("find_credentials requires a string.")
    spans: list[tuple[int, int, str]] = []
    for match in _PEM_BLOCK.finditer(text):
        spans.append((match.start(), match.end(), "CR-PRIVATE-KEY"))
    for rule_id, pattern in _FORMAT_RULES:
        for match in pattern.finditer(text):
            if rule_id == "CR-URL-PASSWORD":
                if _is_placeholder(match.group(1)):
                    continue
                spans.append((match.start(1), match.end(1), rule_id))
            else:
                spans.append((match.start(), match.end(), rule_id))
    for match in _BEARER.finditer(text):
        spans.append((match.start("value"), match.end("value"), "CR-BEARER"))
    for match in (_CODE_ASSIGN if code else _LOOSE_ASSIGN).finditer(text):
        value = match.group("value")
        if len(value) < MIN_ASSIGNED_VALUE or _is_placeholder(value):
            continue
        spans.append((match.start("value"), match.end("value"), "CR-ASSIGN"))

    # Overlapping spans become one span; the earliest-starting, then longest,
    # match names it. Deterministic for a given text.
    spans.sort(key=lambda s: (s[0], -s[1], s[2]))
    merged: list[list] = []
    for start, end, rule_id in spans:
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            continue
        merged.append([start, end, rule_id])
    return tuple(CredentialFlag(rule_id, start, end) for start, end, rule_id in merged)


def redact_credentials(
    text: str, *, code: bool = False
) -> tuple[str, tuple[CredentialFlag, ...]]:
    """Return ``text`` with every credential replaced, and where they were."""

    flags = find_credentials(text, code=code)
    if not flags:
        return text, ()
    parts: list[str] = []
    cursor = 0
    for flag in flags:
        parts.append(text[cursor:flag.start])
        parts.append(REDACTION)
        cursor = flag.end
    parts.append(text[cursor:])
    return "".join(parts), flags
