"""Model-integration boundary for the Software-Engineering QA Agent."""

from .client import (
    ChatCompletionsClient,
    ModelCallResult,
    ModelClient,
    TokenUsage,
)
from ..rag.pipeline import (
    PipelineResult,
    ProposalInput,
    generate_test_proposals,
    parse_json_object,
)

__all__ = [
    "ChatCompletionsClient",
    "ModelCallResult",
    "ModelClient",
    "PipelineResult",
    "ProposalInput",
    "TokenUsage",
    "generate_test_proposals",
    "parse_json_object",
]
