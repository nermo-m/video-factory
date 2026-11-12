"""The language model interface (design doc section 3.3).

One request is one skill call: a prompt in, a text or a JSON document out. An adapter
never decides anything about the pipeline. It answers, measures and reports failures in
the error classes the job queue acts on (section 4.4):

* RetryableError: timeouts, rate limits, a busy or failing service;
* InvalidOutputError: the answer is not what was asked for (not JSON, cut off);
* NeedsOwnerError: only the owner can fix it (a key, a setting, a declined request);
* JobError with the class `bug`: the request itself was wrong.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from packages.core.enums import Provider
from packages.core.queue import InvalidOutputError

DEFAULT_MAX_TOKENS = 16000
_FENCED = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)


@dataclass(frozen=True)
class LLMRequest:
    skill: str
    skill_version: str
    prompt: str
    system: str = ""
    # JSON Schema of the wanted output. None asks for plain text.
    output_schema: Mapping[str, Any] | None = None
    # Let the model search the web (the research skill). Answers then carry their sources.
    web_search: bool = False
    max_searches: int = 5
    # low, medium, high, xhigh or max. None leaves the adapter's default.
    effort: str | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS


@dataclass(frozen=True)
class Source:
    """A passage the model actually retrieved, with where it came from (FR-02)."""

    url: str
    title: str
    cited_text: str


@dataclass(frozen=True)
class LLMResponse:
    output: Any  # the parsed JSON document when a schema was asked for, else the text
    text: str
    provider: Provider
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    sources: tuple[Source, ...] = ()
    searches: int = 0
    request_id: str | None = None


class LLMAdapter(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Answer one request. Raises a JobError subclass when it cannot."""


def request_hash(request: LLMRequest) -> str:
    """A stable SHA-256 of everything that shapes the answer, for `model_call.input_hash`."""
    canonical = json.dumps(
        {
            "skill": request.skill,
            "skill_version": request.skill_version,
            "system": request.system,
            "prompt": request.prompt,
            "output_schema": request.output_schema,
            "web_search": request.web_search,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_json_answer(text: str) -> Any:
    """The JSON document in an answer: the whole text, a fenced block, or its outer braces."""
    candidates = [text.strip()]
    candidates += [block.strip() for block in reversed(_FENCED.findall(text))]
    first, last = text.find("{"), text.rfind("}")
    if 0 <= first < last:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise InvalidOutputError("The model's answer is not a JSON document.")
