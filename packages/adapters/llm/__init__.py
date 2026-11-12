"""Language model adapters: the Anthropic API and its recorded twin (design doc 3.3)."""

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
from packages.adapters.llm.recorded import RecordedLLM

__all__ = [
    "AnthropicLLM",
    "LLMAdapter",
    "LLMRequest",
    "LLMResponse",
    "RecordedLLM",
    "Source",
    "parse_json_answer",
    "request_hash",
]
