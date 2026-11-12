"""Language model adapters (design doc 3.3 and 3.4): recorded answers for demo mode, the
command line tools through the host bridge for subscription mode, and the Anthropic API.
"""

from __future__ import annotations

from packages.adapters.llm.anthropic_api import AnthropicLLM
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
