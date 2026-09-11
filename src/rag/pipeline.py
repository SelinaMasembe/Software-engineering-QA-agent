"""Baseline Week 2 pipeline connecting prompts, evidence, and a model client."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from models.client import (
    IntegrationInputError,
    ModelCallResult,
    ModelClient,
    ModelResponseError,
    TokenUsage,
)

ParsedOutput = TypeVar("ParsedOutput")
ResponseParser = Callable[[str], ParsedOutput]


@dataclass(frozen=True)
class ProposalInput:
    """Explicit evidence passed to the baseline model interaction."""

    requirement_text: str
    source_text: str
    source_path: str
    requirement_id: str | None = None

    def validate(self) -> None:
        if not self.requirement_text.strip():
            raise IntegrationInputError("Requirement text must not be empty.")
        if not self.source_text.strip():
            raise IntegrationInputError("Source text must not be empty.")
        if not self.source_path.strip():
            raise IntegrationInputError("Source path must not be empty.")


@dataclass(frozen=True)
class PipelineResult(Generic[ParsedOutput]):
    """Parsed application result plus evidence about the model interaction."""

    output: ParsedOutput
    raw_text: str
    model: str
    prompt_version: str
    latency_ms: int
    usage: TokenUsage
    request_id: str | None = None


def build_user_content(proposal_input: ProposalInput) -> str:
    """Serialize evidence without adding instructions owned by the prompt author."""

    proposal_input.validate()
    payload = {
        "requirement": {
            "id": proposal_input.requirement_id,
            "text": proposal_input.requirement_text,
        },
        "source": {
            "path": proposal_input.source_path,
            "content": proposal_input.source_text,
        },
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def parse_json_object(raw_text: str) -> dict[str, Any]:
    """Parse a strict JSON object, allowing only an optional Markdown fence."""

    text = raw_text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelResponseError("The model did not return valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise ModelResponseError("The model response must be a JSON object.")
    return parsed


def generate_test_proposals(
    *,
    proposal_input: ProposalInput,
    system_prompt: str,
    prompt_version: str,
    client: ModelClient,
    response_parser: ResponseParser[ParsedOutput] = parse_json_object,
) -> PipelineResult[ParsedOutput]:
    """Run the smallest useful model-backed test-proposal interaction.

    The prompt text and version are supplied by Member 3. The parser may be
    replaced with Member 1's ``ProposalSet.model_validate_json`` method.
    """

    proposal_input.validate()
    if not system_prompt.strip():
        raise IntegrationInputError("System prompt must not be empty.")
    if not prompt_version.strip():
        raise IntegrationInputError("Prompt version must not be empty.")

    call_result: ModelCallResult = client.generate(
        system_prompt=system_prompt,
        user_content=build_user_content(proposal_input),
    )

    try:
        output = response_parser(call_result.raw_text)
    except ModelResponseError:
        raise
    except Exception as exc:
        raise ModelResponseError(
            "The model response failed application-level validation."
        ) from exc

    return PipelineResult(
        output=output,
        raw_text=call_result.raw_text,
        model=call_result.model,
        prompt_version=prompt_version,
        latency_ms=call_result.latency_ms,
        usage=call_result.usage,
        request_id=call_result.request_id,
    )
