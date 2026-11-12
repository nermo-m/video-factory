"""Language model adapters (design doc 3.3 and 3.4): recorded answers for demo mode, the
command line tools through the host bridge for subscription mode, and the Anthropic API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.adapters.llm.base import (
    LLMAdapter,
    LLMRequest,
    LLMResponse,
    Source,
    parse_json_answer,
    request_hash,
)
from packages.adapters.llm.cli_bridge import ClaudeCliLLM, CodexCliLLM
from packages.adapters.llm.recorded import RecordedLLM

__all__ = [
    "AnthropicLLM",
    "ClaudeCliLLM",
    "CodexCliLLM",
    "LLMAdapter",
    "LLMRequest",
    "LLMResponse",
    "RecordedLLM",
    "Source",
    "parse_json_answer",
    "request_hash",
]

if TYPE_CHECKING:
    from packages.adapters.llm.anthropic_api import AnthropicLLM


def __getattr__(name: str) -> Any:
    """Load the Anthropic adapter only when it is asked for.

    It needs the paid SDK, which only the worker installs. The api service uses the
    bridge adapters for the limits check and must be able to import this package.
    """
    if name == "AnthropicLLM":
        from packages.adapters.llm.anthropic_api import AnthropicLLM

        return AnthropicLLM
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
