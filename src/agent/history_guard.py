"""Guard earlier tool output before a planner shows it to the model (finding F8).

Week 8, Member 3. ``build_context`` redacts credentials, neutralises wrapper
tags and flags injection text in retrieved chunks. Tool output stored in the
loop history (read_file content, search_repo chunks, run_tests output) never
passes through ``build_context``, so a planner that renders history must apply
the same guard itself. This module is that guard.

For every string in an observation (output values and keys, the proposal's
arguments and the loop's message):

1. credential-shaped strings are replaced with ``[REDACTED:credential]``
   (``rag.credential_scan``, prose rules, which are the stricter set);
2. an opening or closing ``evidence``, ``memory`` or ``observation`` tag has
   its leading ``<`` neutralised, the same rule ``build_context`` applies,
   plus the ``observation`` tag this module uses as its own wrapper;
3. the original string is run through the injection flagger.

The guarded observation is rendered as JSON inside one
``<observation ...>`` block whose attributes come only from loop enums and
integers. Flags are returned as ``ChunkFlags`` (one per observation) so the
caller can trace them with ``flag_trace_entry``. Flag spans refer to the
individual string they were found in, not to the rendered block.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from rag.credential_scan import CredentialFlag, redact_credentials
from rag.injection_flagging import ChunkFlags, InjectionFlag, flag_text

DEFAULT_HISTORY_CHAR_BUDGET = 12_000
HISTORY_DOC_TYPE = "tool_output"

_WRAPPER_TAG_START = re.compile(
    r"<(?=\s*/?\s*(?:evidence|memory|observation)\b)", re.IGNORECASE
)


@dataclass(frozen=True)
class GuardedText:
    text: str
    flags: tuple[InjectionFlag | CredentialFlag, ...]


def guard_text(text: str) -> GuardedText:
    """Redact, neutralise and flag one string. ``text`` itself is not changed."""

    if not isinstance(text, str):
        raise TypeError("guard_text requires a string.")
    shown, credential_flags = redact_credentials(text, code=False)
    shown = _WRAPPER_TAG_START.sub("&lt;", shown)
    flags = tuple(
        sorted(flag_text(text) + credential_flags, key=lambda f: (f.start, f.rule_id, f.end))
    )
    return GuardedText(shown, flags)


def _guard_value(value: Any, flags: list) -> Any:
    if isinstance(value, str):
        guarded = guard_text(value)
        flags.extend(guarded.flags)
        return guarded.text
    if isinstance(value, dict):
        return {_guard_value(str(k), flags): _guard_value(v, flags) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_guard_value(item, flags) for item in value]
    return value


def _render_one(observation: Any) -> tuple[str, ChunkFlags | None]:
    data = observation.to_dict()
    flags: list = []
    body = _guard_value(
        {"arguments": data["arguments"], "message": data["message"], "output": data["output"]},
        flags,
    )
    code = f' code="{data["code"]}"' if data["code"] else ""
    block = (
        f'<observation iteration="{int(data["iteration"])}" action="{data["action"]}" '
        f'kind="{data["kind"]}"{code}>\n'
        f"{json.dumps(body, ensure_ascii=True, sort_keys=True, default=str)}\n"
        f"</observation>"
    )
    record = None
    if flags:
        record = ChunkFlags(
            f"history#iteration-{int(data['iteration'])}",
            f"tool:{data['action']}",
            HISTORY_DOC_TYPE,
            tuple(flags),
        )
    return block, record


def render_history(
    history: Iterable[Any], *, max_chars: int = DEFAULT_HISTORY_CHAR_BUDGET
) -> tuple[str, tuple[ChunkFlags, ...]]:
    """Render guarded observations, newest kept first when over ``max_chars``.

    Returns the text and the flags of the observations that were rendered.
    An empty history renders as ``("", ())``.
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero.")
    rendered = [_render_one(o) for o in history]
    kept: list[tuple[str, ChunkFlags | None]] = []
    used = 0
    for block, record in reversed(rendered):
        if kept and used + len(block) > max_chars:
            break
        kept.append((block, record))
        used += len(block) + 1
    kept.reverse()
    omitted = len(rendered) - len(kept)
    lines = [f"({omitted} earlier observation(s) omitted)"] if omitted else []
    lines += [block for block, _ in kept]
    flagged = tuple(record for _, record in kept if record is not None)
    return "\n".join(lines), flagged


__all__ = ["GuardedText", "guard_text", "render_history"]
