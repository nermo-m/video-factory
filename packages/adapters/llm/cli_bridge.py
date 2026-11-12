"""Language models of subscription mode: Claude Code and Codex through the host bridge.

Design doc section 3.4, FR-27. The command line tools are signed in on the owner's PC, so
the worker asks the bridge (`tools/cli_bridge`) to run them. One request to the bridge is
one model call. The bridge's contract, `bridge/1`, is described in its README.

* Calls are covered by the owner's plans: cost 0, billing type `plan` (FR-29).
* A usage limit comes back as `plan_limit` and becomes PlanLimitError with the reset time.
  The job then waits. Nothing here can reach a paid API (FR-28).
* The adapters exist in subscription mode only and refuse to be built in another mode.

Claude Code enforces an output schema itself, sent without its `$schema` and `$id` lines,
which the tool refuses. A schema that refers into another file cannot be sent at all. Two
more cases ask for JSON in the prompt
instead and parse the answer here: a research call, because web search and an enforced
schema are not combined in API mode either, and every Codex call, because Codex only
takes schemas written in OpenAI's strict form, which this project's schemas are not.

A research answer carries `sources`: the pages Claude Code's search returned or its fetch
read, as the bridge reports them. The passage of a page is what the tool read from it, or
what the search said about its results.
"""

from __future__ import annotations

import http.client
import json
import logging
import time
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar
from urllib.parse import urlsplit

from packages.adapters.llm.base import LLMRequest, LLMResponse, Source, parse_json_answer
from packages.core.enums import ErrorClass, Provider
from packages.core.queue import (
    InvalidOutputError,
    JobError,
    NeedsOwnerError,
    PlanLimitError,
    RetryableError,
)

logger = logging.getLogger(__name__)

SUBSCRIPTION = "subscription"
# Seconds: one model call, the wait for the tool's turn, and the bridge's own overhead.
CALL_TIMEOUT_S = 600.0
QUEUE_S = 600.0
GRACE_S = 30.0

_RETRYABLE = frozenset({"busy", "timeout", "tool_failed", "internal"})
_NEEDS_OWNER = frozenset({"not_installed", "not_signed_in", "not_plan_sign_in"})


class _BridgeLLM:
    """What the two adapters share: one request to the bridge and the reading of its answer."""

    provider: ClassVar[Provider]
    tool: ClassVar[str]
    title: ClassVar[str]

    def __init__(
        self,
        *,
        mode: str,
        bridge_url: str,
        model: str | None = None,
        timeout_s: float = CALL_TIMEOUT_S,
        queue_s: float = QUEUE_S,
        grace_s: float = GRACE_S,
    ) -> None:
        if mode != SUBSCRIPTION:
            raise NeedsOwnerError(
                f"{self.title} is used in subscription mode only, and PROVIDER_MODE is "
                f"'{mode}'. The app never changes the mode by itself."
            )
        address = urlsplit(bridge_url)
        if address.scheme not in {"http", "https"} or not address.hostname:
            raise NeedsOwnerError(
                f"CLI_BRIDGE_URL must be an http address such as "
                f"http://host.docker.internal:8189, not '{bridge_url}'."
            )
        self.bridge_url = bridge_url.rstrip("/")
        self.model = model or None
        self.timeout_s = timeout_s
        # The bridge may hold a request while the tool is busy and then run the call, so
        # this side waits for both before it gives up.
        self.http_timeout_s = timeout_s + queue_s + grace_s
        self._address = address

    def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        answer = self._post(self._body(request))
        text = answer.get("text")
        usage = answer.get("usage")
        if not isinstance(text, str) or not isinstance(usage, dict):
            raise self._not_the_bridge()

        output: Any = text
        if request.output_schema is not None:
            enforced = answer.get("output")
            output = enforced if isinstance(enforced, dict) else parse_json_answer(text)

        reported = answer.get("model")
        result = LLMResponse(
            output=output,
            text=text,
            provider=self.provider,
            model=reported if isinstance(reported, str) else self.model or f"{self.tool} default",
            input_tokens=_count(usage.get("input_tokens")),
            output_tokens=_count(usage.get("output_tokens")),
            # Covered by the owner's plan.
            cost_usd=Decimal("0"),
            latency_ms=round((time.perf_counter() - started) * 1000),
            sources=_sources(answer.get("sources")),
            searches=_count(answer.get("searches")),
        )
        # Numbers only: never the prompt or the answer.
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
                "request_id": None,
            },
        )
        return result

    def _body(self, request: LLMRequest) -> dict[str, Any]:
        """The request in the bridge's contract. Fields that were not asked for are left out."""
        raise NotImplementedError

    def _common(self, request: LLMRequest, *, prompt: str, effort: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"prompt": prompt, "timeout_s": self.timeout_s}
        if request.system:
            body["system"] = request.system
        if self.model is not None:
            body["model"] = self.model
        if effort is not None:
            body["effort"] = effort
        return body

    def _post(self, body: Mapping[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        connect = (
            http.client.HTTPSConnection
            if self._address.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connect(
            self._address.hostname or "", self._address.port, timeout=self.http_timeout_s
        )
        try:
            connection.request(
                "POST",
                f"{self._address.path.rstrip('/')}/{self.tool}",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            status, raw = response.status, response.read()
        except TimeoutError:
            raise RetryableError(
                f"The host bridge at {self.bridge_url} did not answer within "
                f"{self.http_timeout_s:g} seconds."
            ) from None
        except (OSError, http.client.HTTPException):
            raise NeedsOwnerError(
                f"The host bridge does not answer at {self.bridge_url}. Start it on the PC "
                "with `make bridge-start` (`make up` does it in subscription mode)."
            ) from None
        finally:
            connection.close()

        try:
            answer = json.loads(raw)
        except ValueError:
            raise self._not_the_bridge() from None
        if not isinstance(answer, dict):
            raise self._not_the_bridge()
        if status == 200:
            return answer
        error = answer.get("error")
        if not isinstance(error, dict) or not isinstance(error.get("code"), str):
            raise self._not_the_bridge()
        raise _failure(error)

    def _not_the_bridge(self) -> NeedsOwnerError:
        return NeedsOwnerError(
            f"What answers at {self.bridge_url} is not the bridge. Check CLI_BRIDGE_URL and "
            "CLI_BRIDGE_PORT, and that nothing else uses that port."
        )


class ClaudeCliLLM(_BridgeLLM):
    """LLMAdapter for the planner skills and agent decisions: Claude Code on the owner's plan."""

    provider = Provider.CLAUDE_PLAN
    tool = "claude"
    title = "Claude Code"

    def _body(self, request: LLMRequest) -> dict[str, Any]:
        sendable = tool_schema(request.output_schema) if request.output_schema else None
        enforce = sendable is not None and not request.web_search
        prompt = request.prompt
        if request.output_schema is not None and not enforce:
            prompt = _with_schema(prompt, request.output_schema)
        body = self._common(request, prompt=prompt, effort=request.effort)
        if enforce:
            body["schema"] = sendable
        if request.web_search:
            body["web_search"] = True
        return body


class CodexCliLLM(_BridgeLLM):
    """LLMAdapter for the independent second review: Codex on the owner's ChatGPT plan."""

    provider = Provider.CHATGPT_PLAN
    tool = "codex"
    title = "Codex"
    # The bridge accepts these three for Codex. The two above them become the highest.
    _EFFORTS: ClassVar[dict[str, str]] = {
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "high",
        "max": "high",
    }

    def _body(self, request: LLMRequest) -> dict[str, Any]:
        if request.web_search:
            raise JobError(
                "The second reviewer has no web search. Research goes to the planner's model.",
                error_class=ErrorClass.BUG,
            )
        prompt = request.prompt
        if request.output_schema is not None:
            prompt = _with_schema(prompt, request.output_schema)
        effort = self._EFFORTS.get(request.effort) if request.effort else None
        return self._common(request, prompt=prompt, effort=effort)


def tool_schema(schema: Mapping[str, Any]) -> dict[str, Any] | None:
    """A schema as Claude Code can enforce it, or None when it cannot take it.

    The tool refuses the lines that name the schema's dialect and address (`$schema`,
    `$id`), so they are left out. It cannot follow a reference into another file. Such a
    schema travels in the prompt instead, and the caller checks the answer against it.
    """

    def convert(node: Any) -> Any:
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        converted = {}
        for key, value in node.items():
            if key == "$ref" and not str(value).startswith("#"):
                raise ValueError(value)
            if key not in {"$schema", "$id"}:
                converted[key] = convert(value)
        return converted

    try:
        result: dict[str, Any] = convert(dict(schema))
    except ValueError:
        return None
    return result


def _with_schema(prompt: str, schema: Mapping[str, Any]) -> str:
    """A prompt that also says which JSON document is wanted."""
    written = json.dumps(schema, ensure_ascii=False)
    return (
        f"{prompt}\n\n"
        "Answer with one JSON document and nothing else. It must follow this JSON Schema:\n"
        f"{written}"
    )


def _sources(reported: object) -> tuple[Source, ...]:
    """The pages the tool retrieved (FR-02). Anything that is not one is left out."""
    found = []
    for item in reported if isinstance(reported, list) else []:
        if isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"]:
            found.append(
                Source(
                    url=item["url"],
                    title=str(item.get("title") or ""),
                    cited_text=str(item.get("text") or ""),
                )
            )
    return tuple(found)


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _failure(error: Mapping[str, Any]) -> JobError:
    """A bridge error as the failure the job queue acts on (section 4.4)."""
    code = str(error["code"])
    message = error.get("message")
    words = message if isinstance(message, str) and message else f"The bridge answered '{code}'."
    if code == "plan_limit":
        return PlanLimitError(words, retry_at=_time(error.get("retry_at")))
    if code in _RETRYABLE:
        return RetryableError(words)
    if code == "invalid_output":
        return InvalidOutputError(words)
    if code in _NEEDS_OWNER:
        return NeedsOwnerError(words)
    # A refused request is this side's mistake, and so is a class this side does not know.
    return JobError(f"The bridge refused the request ({code}): {words}", error_class=ErrorClass.BUG)


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None
