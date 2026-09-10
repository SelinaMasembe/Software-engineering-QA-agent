"""Model-integration boundary for the Software-Engineering QA Agent."""

from .model_integration import (
    ChatCompletionsClient,
    ModelCallResult,
    ModelClient,
    TokenUsage,
)
from .pipeline import (
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
