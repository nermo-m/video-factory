"""The Anthropic adapter, driven through the real SDK with a mock transport.

No request leaves the machine: the SDK's HTTP layer is replaced by a function that records
what would have been sent and answers like the API. That checks the request the SDK
really builds (model, output format, web search tool, headers), which a hand-made stand-in
for the client could not. The live check against the real API is a separate, parked card.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import httpx2
import pytest

from packages.adapters.llm import AnthropicLLM, LLMRequest
from packages.adapters.llm.anthropic_api import api_schema
from packages.core.enums import ErrorClass, Provider
from packages.core.logs import JsonFormatter
from packages.core.providers import PaidApiRefusedError
from packages.core.queue import InvalidOutputError, JobError, NeedsOwnerError, RetryableError

PLANTED = "planted-value-that-must-never-be-logged"
SCHEMA = {
    "type": "object",
    "required": ["lesson"],
    "additionalProperties": False,
    "properties": {"lesson": {"type": "string"}},
}
Handler = Callable[[httpx2.Request], httpx2.Response]


def message(
    content: list[dict[str, Any]],
    *,
    stop_reason: str = "end_turn",
    model: str = "claude-opus-5-5",
    usage: dict[str, Any] | None = None,
    **more: Any,
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 1000, "output_tokens": 200},
        **more,
    }


def text(value: str, **more: Any) -> dict[str, Any]:
    return {"type": "text", "text": value, **more}


class Api:
    """Answers like the Messages API and keeps every request it was sent."""

    def __init__(self, *answers: dict[str, Any] | httpx2.Response | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, httpx2.Response):
            return answer
        return httpx2.Response(200, json=answer, headers={"request-id": "req_test"})

    def body(self, index: int = -1) -> dict[str, Any]:
        sent: dict[str, Any] = json.loads(self.requests[index].content)
        return sent


def adapter(api: Api, **options: Any) -> AnthropicLLM:
    return AnthropicLLM(
        mode="api",
        paid_apis_confirmed=True,
        api_key=PLANTED,
        transport=httpx2.MockTransport(api),
        max_retries=0,
        **options,
    )


def ask(**changes: Any) -> LLMRequest:
    fields: dict[str, Any] = {
        "skill": "brief",
        "skill_version": "1.0",
        "system": "You plan short videos.",
        "prompt": "An idea about habits.",
        "output_schema": SCHEMA,
    }
    return LLMRequest(**{**fields, **changes})


def error(status: int, kind: str) -> httpx2.Response:
    return httpx2.Response(
        status, json={"type": "error", "error": {"type": kind, "message": "It failed."}}
    )


# --- FR-28: it cannot exist without mode, switch and key ---------------------------------


@pytest.mark.parametrize(
    ("mode", "confirmed"), [("demo", True), ("subscription", True), ("api", False)]
)
def test_fr28_the_adapter_cannot_be_built_unless_paid_apis_are_switched_on(
    mode: str, confirmed: bool
) -> None:
    api = Api(message([text("{}")]))

    with pytest.raises(PaidApiRefusedError):
        AnthropicLLM(
            mode=mode,
            paid_apis_confirmed=confirmed,
            api_key=PLANTED,
            transport=httpx2.MockTransport(api),
        )

    assert api.requests == []


def test_a_model_without_a_known_price_is_refused_before_any_call() -> None:
    api = Api(message([text("{}")]))

    with pytest.raises(NeedsOwnerError, match="claude-experimental-9"):
        adapter(api, model="claude-experimental-9")


# --- the request -------------------------------------------------------------------------


def test_a_request_asks_the_configured_model_for_the_schema() -> None:
    api = Api(message([text('{"lesson": "Small steps count."}')]))

    adapter(api).complete(ask())

    sent = api.body()
    assert sent["model"] == "claude-opus-5-5"
    assert sent["system"] == "You plan short videos."
    assert sent["messages"] == [{"role": "user", "content": "An idea about habits."}]
    assert sent["max_tokens"] == 16000
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert sent["output_config"]["effort"] == "medium"
    assert "tools" not in sent
    # Thinking is always on for this model and sampling settings are rejected by it.
    assert "thinking" not in sent
    assert "temperature" not in sent


def test_the_key_travels_in_the_authorization_header_and_nowhere_else() -> None:
    api = Api(message([text('{"lesson": "x"}')]))

    adapter(api).complete(ask())

    request = api.requests[0]
    # SDK 2.8.0 sends the key as a bearer token, with API version 2026-10-21.
    assert request.headers["authorization"] == f"Bearer {PLANTED}"
    assert request.headers["anthropic-version"] == "2026-10-21"
    assert [name for name, value in request.headers.items() if PLANTED in value] == [
        "authorization"
    ]
    assert PLANTED not in request.content.decode("utf-8")
    assert PLANTED not in str(request.url)


def test_refusals_are_handed_to_the_fallback_the_api_offers() -> None:
    api = Api(message([text('{"lesson": "x"}')]))

    adapter(api).complete(ask())

    assert api.body()["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in api.requests[0].headers["anthropic-beta"]


def test_research_gets_web_search_and_no_fixed_output_format() -> None:
    api = Api(message([text('{"claims": []}')]))

    adapter(api).complete(ask(skill="research", web_search=True, max_searches=4))

    sent = api.body()
    assert sent["tools"] == [
        {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": 4,
            "allowed_callers": ["direct"],
        }
    ]
    # Search answers carry citations, and the API refuses citations together with a
    # fixed output format. The JSON is asked for in the prompt and parsed here instead.
    assert "format" not in sent["output_config"]


def test_another_model_and_effort_can_be_asked_for() -> None:
    api = Api(message([text('{"lesson": "x"}')], model="claude-sonnet-5-5"))

    adapter(api, model="claude-sonnet-5-5").complete(ask(effort="high", max_tokens=4000))

    sent = api.body()
    assert (sent["model"], sent["max_tokens"]) == ("claude-sonnet-5-5", 4000)
    assert sent["output_config"]["effort"] == "high"


# --- the answer --------------------------------------------------------------------------


def test_the_answer_is_parsed_and_measured() -> None:
    api = Api(message([text('{"lesson": "Small steps count."}')]))

    response = adapter(api).complete(ask())

    assert response.output == {"lesson": "Small steps count."}
    assert response.provider is Provider.ANTHROPIC_API
    assert response.model == "claude-opus-5-5"
    assert (response.input_tokens, response.output_tokens) == (1000, 200)
    assert response.request_id == "req_test"
    assert response.latency_ms >= 0


def test_fr17_cost_is_tokens_times_the_models_price() -> None:
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_read_input_tokens": 500_000,
        "cache_creation_input_tokens": 200_000,
    }
    api = Api(message([text('{"lesson": "x"}')], usage=usage))

    response = adapter(api).complete(ask())

    # Opus 5.5: 4 dollars per million in, 20 out, cache reads 0.20, cache writes 1.25 x in.
    assert response.cost_usd == Decimal("4") + Decimal("2") + Decimal("0.10") + Decimal("1")
    assert response.input_tokens == 1_700_000


def test_fr17_a_web_search_costs_one_cent() -> None:
    usage = {"input_tokens": 0, "output_tokens": 0, "server_tool_use": {"web_search_requests": 3}}
    api = Api(message([text('{"claims": []}')], usage=usage))

    response = adapter(api).complete(ask(skill="research", web_search=True))

    assert response.searches == 3
    assert response.cost_usd == Decimal("0.03")


def test_text_without_a_schema_comes_back_as_text() -> None:
    api = Api(message([text("A plain answer.")]))

    response = adapter(api).complete(ask(output_schema=None))

    assert response.output == "A plain answer."
    assert "format" not in api.body()["output_config"]


def test_fr02_the_passages_the_model_really_retrieved_come_back_with_the_answer() -> None:
    cited = {
        "type": "web_search_result_location",
        "url": "https://example.org/habits",
        "title": "A study of habits",
        "encrypted_index": "abc",
        "cited_text": "Seven in ten kept the habit for thirty days.",
    }
    api = Api(
        message(
            [
                text("I will look that up."),
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_1",
                    "name": "web_search",
                    "input": {"query": "habit study"},
                },
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "srvtoolu_1",
                    "content": [
                        {
                            "type": "web_search_result",
                            "url": "https://example.org/habits",
                            "title": "A study of habits",
                            "encrypted_content": "xyz",
                            "page_age": "May 2026",
                        }
                    ],
                },
                text("Seven in ten kept going.", citations=[cited]),
                text('```json\n{"claims": [{"text": "Seven in ten kept going."}]}\n```'),
            ]
        )
    )

    response = adapter(api).complete(ask(skill="research", web_search=True))

    assert response.output == {"claims": [{"text": "Seven in ten kept going."}]}
    assert [(item.url, item.cited_text) for item in response.sources] == [
        ("https://example.org/habits", "Seven in ten kept the habit for thirty days.")
    ]


def test_a_paused_search_turn_is_sent_back_until_it_finishes() -> None:
    paused = message(
        [text("Searching.")],
        stop_reason="pause_turn",
        usage={"input_tokens": 100, "output_tokens": 10},
    )
    finished = message([text('{"claims": []}')], usage={"input_tokens": 300, "output_tokens": 40})
    api = Api(paused, finished)

    response = adapter(api).complete(ask(skill="research", web_search=True))

    assert len(api.requests) == 2
    resumed = api.body(1)["messages"]
    assert [entry["role"] for entry in resumed] == ["user", "assistant"]
    assert resumed[1]["content"][0]["text"] == "Searching."
    assert response.output == {"claims": []}
    assert (response.input_tokens, response.output_tokens) == (400, 50)


def test_a_turn_that_never_stops_pausing_is_given_up() -> None:
    api = Api(message([text("Searching.")], stop_reason="pause_turn"))

    with pytest.raises(RetryableError, match="paused"):
        adapter(api).complete(ask(skill="research", web_search=True))

    assert len(api.requests) == 4


# --- what can go wrong -------------------------------------------------------------------


def test_an_answer_that_is_not_json_is_invalid_output() -> None:
    api = Api(message([text("Here is what I think, in prose.")]))

    with pytest.raises(InvalidOutputError, match="JSON"):
        adapter(api).complete(ask(skill="research", web_search=True))


def test_an_answer_cut_off_by_the_token_limit_is_invalid_output() -> None:
    api = Api(message([text('{"lesson": "Small st')], stop_reason="max_tokens"))

    with pytest.raises(InvalidOutputError, match="cut off"):
        adapter(api).complete(ask())


def test_a_refusal_goes_to_the_owner_with_its_reason() -> None:
    refused = message(
        [],
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "Not allowed."},
    )
    api = Api(refused)

    with pytest.raises(NeedsOwnerError, match="declined") as caught:
        adapter(api).complete(ask())

    assert "cyber" in str(caught.value)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (error(429, "rate_limit_error"), RetryableError),
        (error(529, "overloaded_error"), RetryableError),
        (error(500, "api_error"), RetryableError),
        (httpx2.ConnectError("no route"), RetryableError),
        (httpx2.ReadTimeout("too slow"), RetryableError),
        (error(401, "authentication_error"), NeedsOwnerError),
        (error(403, "permission_error"), NeedsOwnerError),
        (error(404, "not_found_error"), NeedsOwnerError),
    ],
)
def test_api_failures_become_the_error_class_the_queue_acts_on(
    answer: httpx2.Response | Exception, expected: type[JobError]
) -> None:
    with pytest.raises(expected):
        adapter(Api(answer)).complete(ask())


def test_a_request_the_api_calls_invalid_is_a_bug_not_something_to_retry() -> None:
    with pytest.raises(JobError) as caught:
        adapter(Api(error(400, "invalid_request_error"))).complete(ask())

    assert caught.value.error_class is ErrorClass.BUG


# --- NFR-01: keys never appear in logs ---------------------------------------------------


@pytest.fixture
def everything_logged() -> Iterator[io.StringIO]:
    """Capture every log record of every logger at debug level, as the app formats it."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    before = (root.level, list(root.handlers))
    quiet = {name: logging.getLogger(name).level for name in ("anthropic", "httpx2", "httpcore2")}
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG)
    for name in quiet:
        logging.getLogger(name).setLevel(logging.DEBUG)
    try:
        yield stream
    finally:
        root.setLevel(before[0])
        root.handlers[:] = before[1]
        for name, level in quiet.items():
            logging.getLogger(name).setLevel(level)


def test_nfr01_the_key_never_appears_in_a_log_line(everything_logged: io.StringIO) -> None:
    good = Api(message([text('{"lesson": "x"}')]))
    adapter(good).complete(ask())
    for answer in (error(401, "authentication_error"), error(500, "api_error")):
        with pytest.raises(JobError):
            adapter(Api(answer)).complete(ask())

    logged = everything_logged.getvalue()

    assert "model call" in logged, "the adapter must log each call"
    assert PLANTED not in logged


def test_a_call_is_logged_with_its_numbers_and_without_the_prompt(
    everything_logged: io.StringIO,
) -> None:
    adapter(Api(message([text('{"lesson": "x"}')]))).complete(ask())

    lines = [json.loads(line) for line in everything_logged.getvalue().splitlines()]
    call = next(line for line in lines if line["message"] == "model call")

    assert call["provider"] == "anthropic_api"
    assert call["model"] == "claude-opus-5-5"
    assert (call["skill"], call["input_tokens"], call["output_tokens"]) == ("brief", 1000, 200)
    assert call["request_id"] == "req_test"
    # The app's own line carries numbers only. (The SDK prints whole requests when the
    # log level is set to debug, which is the owner's choice. It never prints the key.)
    assert "An idea about habits." not in json.dumps(call)
    assert "You plan short videos." not in json.dumps(call)


def test_nfr01_the_key_is_not_in_an_error_message_either() -> None:
    with pytest.raises(NeedsOwnerError) as caught:
        adapter(Api(error(401, "authentication_error"))).complete(ask())

    assert PLANTED not in str(caught.value)
    assert "ANTHROPIC_API_KEY" in str(caught.value)


# --- the schema the API can enforce ------------------------------------------------------


def test_constraints_the_api_does_not_enforce_are_left_to_the_caller() -> None:
    full = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["title", "minimum"],
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string", "minLength": 3, "maxLength": 100, "pattern": "^[A-Z]"},
            # A property that happens to be named like a keyword is kept.
            "minimum": {"type": "integer", "minimum": 0, "maximum": 10},
            "tags": {"type": "array", "items": {"$ref": "#/$defs/tag"}, "maxItems": 5},
            "kind": {"oneOf": [{"const": "a"}, {"const": "b"}]},
        },
        "$defs": {"tag": {"type": "string", "maxLength": 20}},
    }

    assert api_schema(full) == {
        "type": "object",
        "required": ["title", "minimum"],
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "minimum": {"type": "integer"},
            "tags": {"type": "array", "items": {"$ref": "#/$defs/tag"}},
            "kind": {"anyOf": [{"const": "a"}, {"const": "b"}]},
        },
        "$defs": {"tag": {"type": "string"}},
    }


def test_a_schema_that_points_into_another_file_is_not_sent_and_the_answer_is_parsed() -> None:
    split = {
        "type": "object",
        "properties": {"scene": {"$ref": "episode_spec.schema.json#/$defs/scene"}},
    }
    api = Api(message([text('Here it is:\n```json\n{"scene": {"id": "s01"}}\n```')]))

    response = adapter(api).complete(ask(output_schema=split))

    assert "format" not in api.body()["output_config"]
    assert response.output == {"scene": {"id": "s01"}}
