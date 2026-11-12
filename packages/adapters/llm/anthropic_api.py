"""The Anthropic adapter: Claude through the paid API (design doc sections 3.3 and 3.4).

It builds on PaidApiAdapter, so it cannot exist unless PROVIDER_MODE is `api`, the owner's
"Use paid APIs" switch is on and a key is set (FR-28).

Written against the Python SDK `anthropic` 2.8.0 and the API documentation of November
2026. What the request relies on:

* Structured output: `output_config.format` with a JSON Schema. The API supports a subset
  of JSON Schema, so `api_schema` removes what it does not enforce. The caller validates
  the answer against the full schema in any case.
* Web search for the research skill: the server tool `web_search_20260209`, called
  directly so every result and citation is in the answer. Search answers always carry
  citations, and the API refuses citations together with a fixed output format, so a
  search request asks for JSON in its prompt and the answer is parsed here.
* Thinking is always on for the default model and is not configured. Depth is set with
  `output_config.effort`.
* A long search turn can stop with `pause_turn`. It is sent back unchanged to continue.
* Refusals: the request opts into the API's server-side fallback, so a request the model
  declines is tried on another model inside the same call. Only when that also declines
  does the job fail, for the owner.

Not checked against the live API yet: that needs a key and a budget from the owner.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import anthropic
import httpx2

from packages.adapters.llm.base import (
    LLMRequest,
    LLMResponse,
    Source,
    parse_json_answer,
)
from packages.adapters.paid import PaidApiAdapter
from packages.core.enums import ErrorClass, Provider
from packages.core.queue import InvalidOutputError, JobError, NeedsOwnerError, RetryableError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
WEB_SEARCH_TOOL = "web_search_20260209"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_RESUMES = 3
TIMEOUT_S = 600.0

_MILLION = Decimal(1_000_000)
# US dollars per million tokens: input, output, cache read. Input and output prices are
# from the published price list of 2026-11-03, as are the cache read prices of the two 5.5
# models. The other cache read prices use the general rule of a tenth of the input price.
# This adapter sets no cache breakpoints, so cache prices only matter if that changes.
# A model that is not listed here cannot be chosen: its cost would be a guess.
PRICES: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20"), Decimal("0.20")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10"), Decimal("0.10")),
    "claude-opus-5": (Decimal("5"), Decimal("25"), Decimal("0.50")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25"), Decimal("0.50")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10"), Decimal("0.20")),
}
CACHE_WRITE_FACTOR = Decimal("1.25")
SEARCH_PRICE = Decimal("0.01")  # 10 dollars per 1000 searches

# JSON Schema keywords the API's structured output does not enforce.
_NOT_ENFORCED = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    }
)


def api_schema(schema: Mapping[str, Any]) -> dict[str, Any] | None:
    """The schema as the API can enforce it, or None when it cannot take it at all.

    Constraints the API does not enforce are removed and `oneOf` becomes `anyOf`. A
    schema that points into another file cannot be sent. The caller still validates the
    answer against the full schema.
    """

    def convert(node: Any) -> Any:
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        converted: dict[str, Any] = {}
        for key, value in node.items():
            if key == "$ref" and not str(value).startswith("#"):
                raise ValueError(value)
            if key in {"properties", "$defs"}:
                # The keys here are names chosen by the schema's author, not keywords.
                converted[key] = {name: convert(child) for name, child in value.items()}
            elif key not in _NOT_ENFORCED and key not in {"$schema", "$id"}:
                converted["anyOf" if key == "oneOf" else key] = convert(value)
        return converted

    try:
        result: dict[str, Any] = convert(dict(schema))
    except ValueError:
        return None
    return result


class AnthropicLLM(PaidApiAdapter):
    """LLMAdapter that calls the Anthropic Messages API."""

    provider = Provider.ANTHROPIC_API
    key_variable = "ANTHROPIC_API_KEY"

    def __init__(
        self,
        *,
        mode: str,
        paid_apis_confirmed: bool,
        api_key: str | None,
        model: str = DEFAULT_MODEL,
        transport: httpx2.BaseTransport | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__(mode=mode, paid_apis_confirmed=paid_apis_confirmed, api_key=api_key)
        if model not in PRICES:
            raise NeedsOwnerError(
                f"ANTHROPIC_MODEL is '{model}', which has no price in this app's table, so "
                f"its cost could not be recorded. Known models: {', '.join(PRICES)}."
            )
        self.model = model
        options: dict[str, Any] = {}
        if transport is not None:
            options["http_client"] = anthropic.DefaultHttpxClient(transport=transport)
        self._client = anthropic.Anthropic(
            api_key=self._key(), max_retries=max_retries, timeout=TIMEOUT_S, **options
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        output_config: dict[str, Any] = {"effort": request.effort or DEFAULT_EFFORT}
        arguments: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "output_config": output_config,
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        if request.system:
            arguments["system"] = request.system
        constrained = False
        if request.web_search:
            arguments["tools"] = [
                {
                    "type": WEB_SEARCH_TOOL,
                    "name": "web_search",
                    "max_uses": request.max_searches,
                    "allowed_callers": ["direct"],
                }
            ]
        elif request.output_schema is not None:
            sendable = api_schema(request.output_schema)
            if sendable is not None:
                output_config["format"] = {"type": "json_schema", "schema": sendable}
                constrained = True

        messages: list[Any] = [{"role": "user", "content": request.prompt}]
        used = _Usage()
        for _ in range(MAX_RESUMES + 1):
            response = self._send(arguments, messages)
            used.add(response)
            if response.stop_reason != "pause_turn":
                break
            # A paused server-tool turn continues when it is sent back as it is.
            messages = [messages[0], {"role": "assistant", "content": response.content}]
        else:
            raise RetryableError(
                f"The model paused {MAX_RESUMES + 1} times without finishing its web search."
            )

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) or "no category given"
            explanation = getattr(details, "explanation", None) or ""
            raise NeedsOwnerError(
                f"The model declined this request ({category}). {explanation}".strip()
            )
        if response.stop_reason == "max_tokens":
            raise InvalidOutputError(
                f"The model's answer was cut off at {request.max_tokens} tokens."
            )

        blocks = [block for block in response.content if block.type == "text"]
        text = "".join(block.text for block in blocks)
        output: Any = text
        if request.output_schema is not None:
            output = parse_json_answer(blocks[0].text if constrained and blocks else text)
        sources = tuple(
            Source(citation.url, citation.title or "", citation.cited_text)
            for block in blocks
            for citation in (block.citations or [])
            if citation.type == "web_search_result_location"
        )

        result = LLMResponse(
            output=output,
            text=text,
            provider=self.provider,
            model=response.model,
            input_tokens=used.input_tokens,
            output_tokens=used.output_tokens,
            cost_usd=used.cost(response.model, self.model),
            latency_ms=round((time.perf_counter() - started) * 1000),
            sources=sources,
            searches=used.searches,
            request_id=getattr(response, "_request_id", None),
        )
        # Numbers only: never the prompt, the answer or anything from the request headers.
        logger.info(
            "model call",
            extra={
                "provider": result.provider.value,
                "model": result.model,
                "skill": request.skill,
                "skill_version": request.skill_version,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "searches": result.searches,
                "cost_usd": str(result.cost_usd),
                "latency_ms": result.latency_ms,
                "request_id": result.request_id,
            },
        )
        return result

    def _send(self, arguments: Mapping[str, Any], messages: list[Any]) -> Any:
        try:
            return self._client.beta.messages.create(**arguments, messages=messages)
        except anthropic.AuthenticationError as error:
            raise NeedsOwnerError(
                "The Anthropic API did not accept the key in ANTHROPIC_API_KEY. "
                "Check the key in .env and restart."
            ) from error
        except anthropic.PermissionDeniedError as error:
            raise NeedsOwnerError(
                "The key in ANTHROPIC_API_KEY is not allowed to do this. Check its "
                "permissions and whether web search is enabled for the organization."
            ) from error
        except anthropic.NotFoundError as error:
            raise NeedsOwnerError(
                f"The Anthropic API does not know the model '{self.model}'. Check ANTHROPIC_MODEL."
            ) from error
        except anthropic.RateLimitError as error:
            raise RetryableError("The Anthropic API rate limit was reached.") from error
        except anthropic.APIStatusError as error:
            if error.status_code >= 500:
                raise RetryableError(
                    f"The Anthropic API is failing or overloaded ({error.status_code})."
                ) from error
            raise JobError(
                f"The Anthropic API rejected the request ({error.status_code}): {error.message}",
                error_class=ErrorClass.BUG,
            ) from error
        except anthropic.APIConnectionError as error:
            # Includes timeouts: no answer arrived.
            raise RetryableError("The Anthropic API could not be reached.") from error


class _Usage:
    """Tokens and searches added up over the requests of one call."""

    def __init__(self) -> None:
        self.plain = 0
        self.cache_read = 0
        self.cache_write = 0
        self.output_tokens = 0
        self.searches = 0

    def add(self, response: Any) -> None:
        usage = response.usage
        self.plain += usage.input_tokens or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", None) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", None) or 0
        self.output_tokens += usage.output_tokens or 0
        tools = getattr(usage, "server_tool_use", None)
        self.searches += getattr(tools, "web_search_requests", None) or 0

    @property
    def input_tokens(self) -> int:
        return self.plain + self.cache_read + self.cache_write

    def cost(self, served_by: str, asked_for: str) -> Decimal:
        """Cost in dollars at the price of the model that answered.

        When a fallback model answered and its price is not in the table, the price of
        the model that was asked for is used and the log says so.
        """
        if served_by not in PRICES:
            logger.warning(
                "no price for the model that answered, using the price of the model asked for",
                extra={"served_by": served_by, "priced_as": asked_for},
            )
        price_in, price_out, price_read = PRICES.get(served_by, PRICES[asked_for])
        tokens = (
            self.plain * price_in
            + self.cache_write * price_in * CACHE_WRITE_FACTOR
            + self.cache_read * price_read
            + self.output_tokens * price_out
        ) / _MILLION
        return tokens + self.searches * SEARCH_PRICE
