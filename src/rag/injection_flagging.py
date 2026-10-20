"""Flag text that looks like an instruction aimed at the agent (risk R1).

R1 says content read from the repository is data, never instructions, and that
text resembling an embedded instruction is "flagged during ingestion for
review". This module is that flagger. It only flags. It never removes, edits
or hides anything: the text a chunk shows the model is unchanged, and a
flagged chunk is still used. A flag tells a human or a later control where to
look; it does not decide anything.

Pure and deterministic: no model call, no file I/O, no clock, no network. A
flag records which rule fired and where (``start`` and ``end`` offsets into
the text it was found in). It never stores the matched text, so a flag record
cannot carry an attacker's string into a log or a trace.

The rules are small regular expressions, written from general injection
patterns and kept deliberately short. They are a first line of defence and
have known limits, listed below. They are not a classifier.

Rule table (``RULES``; the id is stable, the rationale is the one-line reason):

    IO-1  instruction_override   "ignore/forget previous instructions".
    IO-2  instruction_override   "disregard ... earlier/your instructions".
    IO-3  instruction_override   "override the system prompt".
    IO-4  instruction_override   "ignore the above", "disregard everything
                                 above", "ignore all of the above", with no
                                 noun needed after "above".
    IO-5  instruction_override   "from now on you are ...", "you are now" plus
                                 a role noun (assistant, agent, admin, root,
                                 developer), and "pretend to be" or "pretend
                                 (that) you are".
    AI-1  action_imperative_aimed_at_agent
                                 "note to the AI/agent: ...", a message
                                 addressed to the agent, not to a developer.
    AI-2  action_imperative_aimed_at_agent
                                 an "agent:" or "ai:" address followed on the
                                 same line by an action verb.
    AI-3  action_imperative_aimed_at_agent
                                 "you must delete/merge/push/..." second-person
                                 command with a high-risk verb, as opposed to
                                 "the system must ...". Narrowed in Week 8: an
                                 everyday verb ("you should run the tests",
                                 "you will call this endpoint") no longer
                                 fires.
    AI-4  action_imperative_aimed_at_agent
                                 "do not tell/inform the user", "don't mention
                                 this to the user", "without telling the
                                 user": hiding an action from the user.
    AI-5  action_imperative_aimed_at_agent
                                 "reveal/print/show/repeat" followed within a
                                 short span by "system prompt" or "your
                                 instructions".
    RM-1  role_marker            chat-template tokens such as "<|im_start|>".
    RM-2  role_marker            a line that begins "system:" or "assistant:".
    TB-1  tag_breakout           an evidence or memory wrapper tag in content.
    TB-2  tag_breakout           a "<system>" or "<instructions>" style tag.
    HC-1  hidden_characters      zero-width, bidirectional-control or tag
                                 characters, which hide text from a reviewer
                                 (a byte-order mark as the very first
                                 character is ordinary and not flagged).
                                 Narrowed in Week 8: a zero-width joiner
                                 between two emoji or symbols, and a left-to-
                                 right or right-to-left mark next to a
                                 right-to-left letter, are ordinary and not
                                 flagged.
    HM-1  hidden_markup          an HTML comment ("<!-- ... -->", hidden when
                                 rendered) that holds an action verb or an
                                 address to the agent (agent, assistant, ai,
                                 llm). A plain comment does not fire.

Known limits (asserted in tests/test_injection_flagging.py, not failures):
a paraphrase ("kindly set aside what you were told earlier"), an instruction in
another language, and an encoded payload (base64, rot13) are NOT detected.
Since the Week 8 narrowing, "you must run ..." with no agent address is not
flagged either, and neither is an HTML comment that is never closed. Rules
also fire on ordinary text that happens to match, for example documentation
that mentions the ``<evidence>`` tag, a config line "system: linux", a sentence
such as "mocks pretend to be the service", or a requirement "do not tell the
user whether the account exists". Flags are for review, so a false positive
costs a look, and they are never used to drop content.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Optional, Protocol

from models.types import Actor, TraceEntry

from .credential_scan import CredentialFlag

CATEGORIES = (
    "instruction_override",
    "action_imperative_aimed_at_agent",
    "role_marker",
    "tag_breakout",
    "hidden_characters",
    "hidden_markup",
)

TRACE_ACTION = "injection_flagged"

_VERBS = (
    r"run|execute|delete|remove|send|call|open|draft|skip|ignore|print|reveal|"
    r"merge|deploy|push|disable|approve|mark|submit|exfiltrate"
)

# AI-3 only: verbs whose effect is hard to undo or leaves the repository.
# Everyday documentation verbs (run, execute, call, open, print, mark, draft,
# skip, ignore) are left out, because "you should run the tests" is a
# developer instruction, not an attack.
_HIGH_RISK_VERBS = (
    r"delete|remove|send|exfiltrate|reveal|merge|deploy|push|disable|approve|submit"
)

# HM-1: one HTML comment. The body may not cross "-->" or a new "<!--", so
# each character is scanned from at most one opening and the match stays
# linear even for thousands of unclosed openings. The words that make a
# comment worth flagging are checked separately, on the match only.
_HTML_COMMENT = r"<!--(?:(?!-->|<!--)[\s\S])*-->"
_COMMENT_TRIGGER = re.compile(r"\b(?:" + _VERBS + r"|agent|assistant|ai|llm)\b", re.IGNORECASE)

# Zero-width and joiner characters, bidirectional controls and the Unicode tag
# block: all invisible or reordering, so they can hide an instruction from a
# human reviewer while the model still reads it.
_HIDDEN = (
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069"
    "\U000e0000-\U000e007f]"
    # A byte-order mark is only hidden text when it is not the first character.
    r"|(?<=[\s\S])\ufeff"
)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    pattern: "re.Pattern[str]"
    rationale: str
    # Optional: given the text and a match, True when the match is ordinary in
    # its context and is not flagged. Used by HC-1 and HM-1.
    exempt: Optional[Callable[[str, "re.Match[str]"], bool]] = None


def _rule(rule_id: str, category: str, pattern: str, rationale: str, *, flags: int = 0) -> Rule:
    return Rule(rule_id, category, re.compile(pattern, re.IGNORECASE | flags), rationale)


_ZWJ = "\u200d"
_DIRECTION_MARKS = ("\u200e", "\u200f")
_VARIATION_SELECTORS = ("\ufe0e", "\ufe0f")


def _is_symbol(char: str) -> bool:
    """An emoji or other symbol, or an emoji skin-tone modifier."""

    return unicodedata.category(char) == "So" or "\U0001f3fb" <= char <= "\U0001f3ff"


def _is_right_to_left(char: str) -> bool:
    """A letter from a right-to-left script such as Arabic or Hebrew."""

    return unicodedata.bidirectional(char) in ("R", "AL")


def _ordinary_hidden_character(text: str, match: "re.Match[str]") -> bool:
    """True for the two ordinary uses of HC-1 characters.

    A zero-width joiner between two symbols builds one emoji (a family or a
    profession emoji, for example); a variation selector may sit just before
    it. A left-to-right or right-to-left mark next to a right-to-left letter
    keeps mixed-direction text in order. Anywhere else they are flagged.
    """

    char, start, end = match.group(), match.start(), match.end()
    before = start - 1
    if char == _ZWJ:
        while before >= 0 and text[before] in _VARIATION_SELECTORS:
            before -= 1
        return (
            before >= 0 and end < len(text)
            and _is_symbol(text[before]) and _is_symbol(text[end])
        )
    if char in _DIRECTION_MARKS:
        return (before >= 0 and _is_right_to_left(text[before])) or (
            end < len(text) and _is_right_to_left(text[end])
        )
    return False


def _plain_comment(text: str, match: "re.Match[str]") -> bool:
    """True for an HTML comment with no action verb and no agent address."""

    return _COMMENT_TRIGGER.search(match.group()) is None


RULES: tuple[Rule, ...] = (
    _rule(
        "IO-1", "instruction_override",
        r"\b(?:ignore|forget)\s+(?:all\s+|any\s+|the\s+|your\s+)?"
        r"(?:previous|prior|above|earlier|preceding)\s+"
        r"(?:instructions?|prompts?|rules|directions|messages)\b",
        "Tells the reader to drop the instructions it was given.",
    ),
    _rule(
        "IO-2", "instruction_override",
        r"\bdisregard\b[^.\n]{0,40}\b(?:previous|prior|earlier|above|all|your|the)\b"
        r"[^.\n]{0,20}\b(?:instructions?|rules|guidelines|prompts?)\b",
        "Asks the reader to disregard its instructions.",
    ),
    _rule(
        "IO-3", "instruction_override",
        r"\boverrid(?:e|ing)\s+(?:the\s+|your\s+)?"
        r"(?:system\s+prompt|previous\s+instructions?|safety\s+(?:rules|checks))\b",
        "Claims to override the system prompt or safety rules.",
    ),
    _rule(
        "IO-4", "instruction_override",
        r"\b(?:ignore|disregard)\s+(?:the|everything|all\s+of\s+the)\s+above\b(?!-)",
        "Tells the reader to drop everything above, with no noun needed.",
    ),
    _rule(
        "IO-5", "instruction_override",
        r"\bfrom\s+now\s+on\s*,?\s*you\s+are\b"
        r"|\byou\s+are\s+now\s+(?:(?:a|an|the|in)\s+)?(?:[a-z-]+\s+)?"
        r"(?:assistant|agent|admin|administrator|root|developer)s?\b"
        r"|\bpretend\s+(?:to\s+be|(?:that\s+)?you\s+are)\b",
        "Tries to give the reader a new identity or role.",
    ),
    _rule(
        "AI-1", "action_imperative_aimed_at_agent",
        r"\b(?:note|message|instructions?|attention)s?\s+(?:to|for)\s+(?:the\s+)?"
        r"(?:ai|agent|assistant|llm|model|bot)\b",
        "A message addressed to the agent rather than to a developer.",
    ),
    _rule(
        "AI-2", "action_imperative_aimed_at_agent",
        r"\b(?:ai|agent|assistant|llm)\s*:[^\n]{0,80}?\b(?:" + _VERBS + r")\b",
        "An address to the agent followed, on the same line, by an action verb.",
    ),
    _rule(
        "AI-3", "action_imperative_aimed_at_agent",
        r"\byou\s+(?:must|should|need\s+to|have\s+to|are\s+to|will)\s+(?:now\s+|immediately\s+)?"
        r"(?:" + _HIGH_RISK_VERBS + r")\b",
        "A second-person command with a high-risk verb, unlike a requirement about 'the system'.",
    ),
    _rule(
        "AI-4", "action_imperative_aimed_at_agent",
        r"\b(?:do\s+not|don['\u2019]?t)\s+"
        r"(?:tell|inform|mention\s+(?:this\s+|it\s+|that\s+|anything\s+)?to)\s+(?:the\s+)?users?\b"
        r"|\bwithout\s+(?:telling|informing)\s+(?:the\s+)?users?\b",
        "Asks the reader to hide something from the user.",
    ),
    _rule(
        "AI-5", "action_imperative_aimed_at_agent",
        r"\b(?:reveal|print|show|repeat)\b[^.\n]{0,30}?"
        r"\b(?:system\s+prompt|your\s+instructions)\b",
        "Asks the reader to disclose its system prompt or instructions.",
    ),
    _rule(
        "RM-1", "role_marker",
        r"<\|(?:im_start|im_end|system|assistant|user)\|>|\[/?INST\]|<<\s*/?SYS\s*>>",
        "Chat-template tokens that mark a speaker turn.",
    ),
    _rule(
        "RM-2", "role_marker",
        # The second whitespace run only follows a comment or quote marker, so
        # the two runs can never split one stretch of spaces between them
        # (the earlier form backtracked quadratically on a long blank line).
        r"^[ \t]*(?:(?:#|//|\*|-|>)[ \t]*)?(?:system|assistant)(?:\s+prompt)?[ \t]*:",
        "A line that begins as a system or assistant turn.",
        flags=re.MULTILINE,
    ),
    _rule(
        "TB-1", "tag_breakout",
        r"<\s*/?\s*(?:evidence|memory)\b",
        "An evidence or memory wrapper tag inside content, trying to end or forge a block.",
    ),
    _rule(
        "TB-2", "tag_breakout",
        r"<\s*/?\s*(?:system|instructions?|prompt)\s*>",
        "A system or instruction pseudo-tag inside content.",
    ),
    Rule(
        "HC-1", "hidden_characters", re.compile(_HIDDEN),
        "Invisible or direction-changing characters that hide text from a reviewer.",
        exempt=_ordinary_hidden_character,
    ),
    Rule(
        "HM-1", "hidden_markup", re.compile(_HTML_COMMENT),
        "An HTML comment, hidden when rendered, that holds an action verb or an agent address.",
        exempt=_plain_comment,
    ),
)


@dataclass(frozen=True)
class InjectionFlag:
    """Where a rule fired. Never holds the matched text."""

    rule_id: str
    category: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}.")
        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise ValueError("rule_id must be a non-empty string.")
        for name in ("start", "end"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        if self.end < self.start:
            raise ValueError("end must not be before start.")


@dataclass(frozen=True)
class ChunkFlags:
    """The flags found in one chunk. ``source_path`` is metadata, not text.

    ``flags`` holds injection flags (R1) and, when ``build_context`` made the
    record, credential flags (R4, ``credential_scan.CredentialFlag``).
    """

    chunk_id: str
    source_path: str
    doc_type: str
    flags: tuple[InjectionFlag | CredentialFlag, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "flags", tuple(self.flags))


class _Chunk(Protocol):
    chunk_id: str
    source_path: str
    text: str


def flag_text(text: str) -> tuple[InjectionFlag, ...]:
    """Every rule match in ``text``, ordered by position then rule id."""

    if not isinstance(text, str):
        raise TypeError("flag_text requires a string.")
    found = [
        InjectionFlag(rule.rule_id, rule.category, match.start(), match.end())
        for rule in RULES
        for match in rule.pattern.finditer(text)
        if rule.exempt is None or not rule.exempt(text, match)
    ]
    return tuple(sorted(found, key=lambda f: (f.start, f.rule_id, f.end)))


def flag_chunks(chunks: Iterable[_Chunk]) -> tuple[ChunkFlags, ...]:
    """Flag each chunk's text. Only chunks with at least one flag are returned."""

    flagged: list[ChunkFlags] = []
    for chunk in chunks:
        flags = flag_text(chunk.text)
        if flags:
            doc_type = getattr(chunk.doc_type, "value", str(chunk.doc_type))
            flagged.append(ChunkFlags(chunk.chunk_id, chunk.source_path, doc_type, flags))
    return tuple(flagged)


def flag_trace_entry(
    session_id: str, flagged: Iterable[ChunkFlags], timestamp: datetime
) -> TraceEntry:
    """Build the trace entry that records "these chunks were flagged".

    Nothing calls this yet. Whoever wires a real sensor to a trace sink can
    pass the result to ``sink.record``. The detail holds counts, rule ids and
    categories only: no chunk text, and no source path, because a path comes
    from the content being flagged.
    """

    records = tuple(flagged)
    if not records:
        raise ValueError("There are no flags to record.")
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
        raise ValueError("timestamp must be a timezone-aware datetime.")
    rules = sorted({flag.rule_id for record in records for flag in record.flags})
    categories = sorted({flag.category for record in records for flag in record.flags})
    count = sum(len(record.flags) for record in records)
    detail = (
        f"chunks_flagged={len(records)}; flags={count}; "
        f"categories={','.join(categories)}; rules={','.join(rules)}"
    )
    return TraceEntry(
        session_id=session_id,
        actor=Actor.DETERMINISTIC,
        action=TRACE_ACTION,
        detail=detail,
        timestamp=timestamp,
    )
