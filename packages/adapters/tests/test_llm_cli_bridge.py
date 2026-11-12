"""The language model adapters of subscription mode (section 3.4, FR-27, FR-28, FR-29).

`ClaudeCliLLM` and `CodexCliLLM` call the host bridge, which runs the command line tools.
Two kinds of tests:

* through a real bridge on a free port, with the fake `claude` and `codex` programs of the
  bridge's own tests, so the whole path from request to tool and back is exercised;
* against a stub that answers with each error class of the bridge contract, so every class
  is shown to reach the job queue as the right kind of failure.

No test starts a real tool, so no test can spend plan usage.
"""

from __future__ import annotations

import contextlib
import http.server
import io
import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from packages.adapters.factory import Adapters
from packages.adapters.llm import ClaudeCliLLM, CodexCliLLM, LLMRequest, RecordedLLM
from packages.core import logs
from packages.core.enums import ErrorClass, Provider
from packages.core.queue import (
    InvalidOutputError,
    JobError,
    NeedsOwnerError,
    PlanLimitError,
    RetryableError,
)
from packages.core.settings import Settings
from tools.cli_bridge.config import BridgeConfig
from tools.cli_bridge.server import make_server
from tools.cli_bridge.service import Bridge
from tools.cli_bridge.tests.support import MISSING, NOW, after, calls, fake

SCHEMA = {
    "type": "object",
    "properties": {"lesson": {"type": "string"}, "beats": {"type": "integer"}},
    "required": ["lesson", "beats"],
    "additionalProperties": False,
}
REVIEW = {
    "type": "object",
    "properties": {"score": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
}


def ask(prompt: str = "An idea about a lighthouse keeper.", **fields: Any) -> LLMRequest:
    return LLMRequest(skill="brief", skill_version="1", prompt=prompt, **fields)


@contextlib.contextmanager
def serve(server: http.server.HTTPServer) -> Iterator[str]:
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def bridge_with(
    claude: tuple[str, ...] = MISSING, codex: tuple[str, ...] = MISSING
) -> contextlib.AbstractContextManager[str]:
    """A real bridge with fake tools, as its address."""
    config = BridgeConfig(claude_command=claude, codex_command=codex)
    return serve(make_server(Bridge(config, clock=lambda: NOW), port=0))


@pytest.fixture
def record(tmp_path: Path) -> Path:
    return tmp_path / "record.jsonl"


@pytest.fixture
def bridge(record: Path) -> Iterator[str]:
    """A bridge whose tools answer with a plain text."""
    with bridge_with(
        claude=fake("claude", output="claude_text.json", record=record),
        codex=fake("codex", output="codex_text.jsonl", record=record),
    ) as url:
        yield url


@pytest.fixture
def structured_bridge(record: Path) -> Iterator[str]:
    """A bridge whose tools answer with a JSON document."""
    with bridge_with(
        claude=fake("claude", output="claude_structured.json", record=record),
        codex=fake("codex", output="codex_structured.jsonl", record=record),
    ) as url:
        yield url


def claude(url: str, **options: Any) -> ClaudeCliLLM:
    return ClaudeCliLLM(mode="subscription", bridge_url=url, **options)


def codex(url: str, **options: Any) -> CodexCliLLM:
    return CodexCliLLM(mode="subscription", bridge_url=url, **options)


# --- Through a real bridge ---------------------------------------------------------------


def test_fr27_a_claude_call_goes_through_the_bridge_to_the_tool(bridge: str, record: Path) -> None:
    answer = claude(bridge).complete(ask(system="You plan short videos."))

    (call,) = calls(record)
    assert call["stdin"] == "An idea about a lighthouse keeper."
    assert call["files"][after(call["argv"], "--system-prompt-file")] == "You plan short videos."
    assert answer.text == "A lighthouse keeper counts the ships he brought home."
    assert answer.output == answer.text


def test_fr29_a_plan_call_costs_nothing_and_names_its_provider(bridge: str) -> None:
    answer = claude(bridge).complete(ask())

    assert answer.provider is Provider.CLAUDE_PLAN
    assert answer.cost_usd == Decimal("0")
    assert answer.model == "claude-opus-5-5"
    assert (answer.input_tokens, answer.output_tokens) == (412, 18)
    assert answer.latency_ms >= 0
    assert answer.sources == ()


def test_a_schema_is_enforced_by_the_tool_and_the_document_comes_back(
    structured_bridge: str, record: Path
) -> None:
    answer = claude(structured_bridge).complete(ask(output_schema=SCHEMA))

    (call,) = calls(record)
    assert json.loads(after(call["argv"], "--json-schema")) == SCHEMA
    assert answer.output == {"lesson": "Small lights matter.", "beats": 3}


def test_the_chosen_model_and_effort_reach_the_tool(bridge: str, record: Path) -> None:
    claude(bridge, model="claude-sonnet-5-5").complete(ask(effort="high"))

    (call,) = calls(record)
    assert after(call["argv"], "--model") == "claude-sonnet-5-5"
    assert after(call["argv"], "--effort") == "high"


def test_without_a_chosen_model_the_tool_uses_its_own(bridge: str, record: Path) -> None:
    claude(bridge).complete(ask())

    (call,) = calls(record)
    assert "--model" not in call["argv"]
    assert "--effort" not in call["argv"]


def test_a_research_call_may_search_and_its_answer_is_parsed_here(record: Path) -> None:
    tool = fake("claude", output="claude_search.json", record=record)
    with bridge_with(claude=tool) as url:
        answer = claude(url).complete(ask(web_search=True, output_schema={"type": "object"}))

    (call,) = calls(record)
    assert after(call["argv"], "--tools") == "WebSearch,WebFetch"
    # Search and a tool-enforced schema are not combined, as in API mode: the prompt
    # carries the schema and the answer is parsed by the adapter.
    assert "--json-schema" not in call["argv"]
    assert '"type":"object"' in call["stdin"].replace(" ", "")
    assert answer.output == {
        "claims": [{"id": "c1", "text": "The first lighthouse stood at Alexandria."}]
    }
    assert answer.searches == 3


def test_fr27_a_codex_call_goes_through_the_bridge_to_the_tool(bridge: str, record: Path) -> None:
    answer = codex(bridge, model="gpt-5.5").complete(
        ask("Review this script.", system="You are a strict reviewer.", effort="high")
    )

    (call,) = calls(record)
    assert call["stdin"] == "You are a strict reviewer.\n\nReview this script."
    assert after(call["argv"], "--model") == "gpt-5.5"
    assert 'model_reasoning_effort="high"' in call["argv"]
    assert answer.text == "The hook is strong, the ending is flat."
    assert answer.provider is Provider.CHATGPT_PLAN
    assert answer.cost_usd == Decimal("0")
    assert answer.model == "gpt-5.5"
    assert (answer.input_tokens, answer.output_tokens) == (2400, 52)


def test_codex_without_a_chosen_model_is_recorded_as_the_tools_default(bridge: str) -> None:
    assert codex(bridge).complete(ask()).model == "codex default"


def test_a_codex_schema_travels_in_the_prompt_and_the_answer_is_parsed_here(
    structured_bridge: str, record: Path
) -> None:
    answer = codex(structured_bridge).complete(ask("Review this.", output_schema=REVIEW))

    (call,) = calls(record)
    # Codex only takes schemas written in a stricter form than this project's.
    assert "--output-schema" not in call["argv"]
    assert call["stdin"].startswith("Review this.")
    assert '"score"' in call["stdin"]
    assert answer.output == {"score": 7, "reason": "Clear, a little slow."}


@pytest.mark.parametrize("effort", ["xhigh", "max"])
def test_codex_gets_its_highest_effort_for_the_two_it_does_not_know(
    bridge: str, record: Path, effort: str
) -> None:
    codex(bridge).complete(ask(effort=effort))

    (call,) = calls(record)
    assert 'model_reasoning_effort="high"' in call["argv"]


def test_codex_cannot_search_the_web(bridge: str, record: Path) -> None:
    with pytest.raises(JobError) as raised:
        codex(bridge).complete(ask(web_search=True))

    assert raised.value.error_class is ErrorClass.BUG
    assert calls(record) == []


def test_fr29_a_usage_limit_pauses_the_job_until_the_reset_time() -> None:
    tool = fake("claude", output="claude_limit_session.json", exit_code=1)
    with bridge_with(claude=tool) as url, pytest.raises(PlanLimitError) as raised:
        claude(url).complete(ask())

    assert raised.value.error_class is ErrorClass.PLAN_LIMIT
    assert raised.value.retry_at == datetime(
        2026, 11, 12, 15, 0, tzinfo=timezone(timedelta(hours=2))
    )
    assert "session limit" in str(raised.value)


@pytest.mark.parametrize(("sign_in", "words"), [("none", "claude auth login"), ("api", "plan")])
def test_fr28_a_tool_without_a_plan_sign_in_is_an_owner_task(
    record: Path, sign_in: str, words: str
) -> None:
    tool = fake("claude", output="claude_text.json", record=record, sign_in=sign_in)
    with bridge_with(claude=tool) as url, pytest.raises(NeedsOwnerError, match=words):
        claude(url).complete(ask())

    assert calls(record) == []


def test_a_tool_that_is_not_installed_is_an_owner_task() -> None:
    with bridge_with() as url, pytest.raises(NeedsOwnerError, match="CODEX_BIN"):
        codex(url).complete(ask())


def test_an_answer_that_ignores_the_schema_is_invalid_output() -> None:
    tool = fake("claude", output="claude_schema_missing.json")
    with bridge_with(claude=tool) as url, pytest.raises(InvalidOutputError):
        claude(url).complete(ask(output_schema=SCHEMA))


def test_a_codex_answer_that_is_not_json_is_invalid_output() -> None:
    tool = fake("codex", output="codex_schema_missing.jsonl")
    with bridge_with(codex=tool) as url, pytest.raises(InvalidOutputError):
        codex(url).complete(ask(output_schema=REVIEW))


def test_a_failing_tool_is_retried() -> None:
    tool = fake("codex", output="codex_failed.jsonl", exit_code=1)
    with (
        bridge_with(codex=tool) as url,
        pytest.raises(RetryableError, match="stream disconnected"),
    ):
        codex(url).complete(ask())


def test_a_call_that_takes_too_long_is_stopped_by_the_bridge_and_retried(record: Path) -> None:
    tool = fake("claude", output="claude_text.json", record=record, sleep=30)
    started = time.monotonic()
    with bridge_with(claude=tool) as url, pytest.raises(RetryableError):
        claude(url, timeout_s=0.5).complete(ask())

    assert time.monotonic() - started < 20


# --- Against a stub that speaks the bridge contract -----------------------------------------


class Stub(http.server.BaseHTTPRequestHandler):
    """Answers every request with what the test put in `answer`, and keeps the request."""

    answer: tuple[int, Any] = (200, {})
    delay = 0.0
    seen: list[dict[str, Any]]

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.seen.append(
            {
                "path": self.path,
                "headers": {name.lower(): value for name, value in self.headers.items()},
                "body": json.loads(self.rfile.read(length) or b"null"),
            }
        )
        time.sleep(self.delay)
        status, body = self.answer
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        # A caller that gave up waiting is gone by now, which is what its test is about.
        with contextlib.suppress(OSError):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        return


@contextlib.contextmanager
def stub(
    status: int, body: Any, *, delay: float = 0.0
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Something that answers like the bridge. Yields its address and what it was sent."""
    seen: list[dict[str, Any]] = []
    handler = type("Handler", (Stub,), {"answer": (status, body), "delay": delay, "seen": seen})
    with serve(http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)) as url:
        yield url, seen


def failure(code: str, message: str = "The tool's own words.", **more: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "tool": "claude", "retry_at": None, **more}}


OK = {
    "tool": "claude",
    "output": None,
    "text": "Fine.",
    "model": None,
    "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 2},
    "searches": 0,
    "turns": 1,
    "duration_ms": 5,
    "tool_duration_ms": 4,
    "billing": "plan",
}


def test_the_request_follows_the_bridge_contract() -> None:
    with stub(200, {**OK, "output": {"lesson": "Small lights matter.", "beats": 3}}) as (url, seen):
        claude(url, model="opus", timeout_s=120).complete(
            ask("An idea.", system="Plan.", output_schema=SCHEMA, effort="low")
        )

    (request,) = seen
    assert request["path"] == "/claude"
    assert request["headers"]["content-type"] == "application/json"
    # The bridge refuses anything that looks like it came from a web page.
    assert "origin" not in request["headers"]
    assert request["body"] == {
        "prompt": "An idea.",
        "system": "Plan.",
        "schema": SCHEMA,
        "model": "opus",
        "effort": "low",
        "timeout_s": 120,
    }


def test_the_smallest_request_carries_only_what_was_asked() -> None:
    with stub(200, {**OK, "tool": "codex"}) as (url, seen):
        codex(url).complete(ask("Review this."))

    (request,) = seen
    assert request["path"] == "/codex"
    assert set(request["body"]) == {"prompt", "timeout_s"}


def test_a_claude_call_without_a_reported_model_is_recorded_as_the_tools_default() -> None:
    with stub(200, OK) as (url, _):
        assert claude(url).complete(ask()).model == "claude default"


@pytest.mark.parametrize(
    ("status", "code", "raised", "error_class"),
    [
        (429, "plan_limit", PlanLimitError, ErrorClass.PLAN_LIMIT),
        (503, "busy", RetryableError, ErrorClass.RETRYABLE),
        (504, "timeout", RetryableError, ErrorClass.RETRYABLE),
        (502, "tool_failed", RetryableError, ErrorClass.RETRYABLE),
        (500, "internal", RetryableError, ErrorClass.RETRYABLE),
        (502, "invalid_output", InvalidOutputError, ErrorClass.INVALID_OUTPUT),
        (503, "not_installed", NeedsOwnerError, ErrorClass.NEEDS_OWNER),
        (503, "not_signed_in", NeedsOwnerError, ErrorClass.NEEDS_OWNER),
        (503, "not_plan_sign_in", NeedsOwnerError, ErrorClass.NEEDS_OWNER),
        (400, "bad_request", JobError, ErrorClass.BUG),
        (403, "forbidden", JobError, ErrorClass.BUG),
        (413, "payload_too_large", JobError, ErrorClass.BUG),
        (418, "something_new", JobError, ErrorClass.BUG),
    ],
)
def test_every_error_class_of_the_bridge_reaches_the_queue_as_the_right_failure(
    status: int, code: str, raised: type[JobError], error_class: ErrorClass
) -> None:
    with stub(status, failure(code)) as (url, _), pytest.raises(raised) as caught:
        claude(url).complete(ask())

    assert caught.value.error_class is error_class
    assert "The tool's own words." in str(caught.value)


def test_fr29_a_limit_without_a_reset_time_still_pauses_the_job() -> None:
    with (
        stub(429, failure("plan_limit", "You've hit your weekly limit")) as (url, _),
        pytest.raises(PlanLimitError) as raised,
    ):
        claude(url).complete(ask())

    assert raised.value.retry_at is None


def test_fr29_a_reset_time_that_cannot_be_read_is_left_out() -> None:
    with (
        stub(429, failure("plan_limit", retry_at="next Tuesday")) as (url, _),
        pytest.raises(PlanLimitError) as raised,
    ):
        claude(url).complete(ask())

    assert raised.value.retry_at is None


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_a_bridge_that_is_not_running_is_an_owner_task_that_says_how_to_start_it() -> None:
    url = f"http://127.0.0.1:{free_port()}"

    with pytest.raises(NeedsOwnerError, match="make bridge-start") as raised:
        claude(url).complete(ask())

    assert url in str(raised.value)


@pytest.mark.parametrize("body", [b"<html>Welcome</html>", b"[]", b'{"hello": "world"}'])
def test_something_else_on_the_bridge_port_is_an_owner_task(body: bytes) -> None:
    with stub(200, body) as (url, _), pytest.raises(NeedsOwnerError, match="not the bridge"):
        claude(url).complete(ask())


def test_a_bridge_that_does_not_answer_in_time_is_retried() -> None:
    with (
        stub(200, OK, delay=3) as (url, _),
        pytest.raises(RetryableError, match="did not answer"),
    ):
        claude(url, timeout_s=0.2, queue_s=0.1, grace_s=0.2).complete(ask())


def test_the_adapter_waits_longer_than_the_bridge_may_take() -> None:
    adapter = claude("http://127.0.0.1:8189", timeout_s=600, queue_s=600)

    assert adapter.http_timeout_s > 1200


# --- The mode decides, and only the mode --------------------------------------------------


@pytest.mark.parametrize("mode", ["demo", "api"])
@pytest.mark.parametrize("adapter", [ClaudeCliLLM, CodexCliLLM])
def test_fr28_the_adapters_exist_in_subscription_mode_only(adapter: Any, mode: str) -> None:
    with pytest.raises(NeedsOwnerError, match="subscription"):
        adapter(mode=mode, bridge_url="http://127.0.0.1:8189")


@pytest.mark.parametrize(
    "url", ["ftp://127.0.0.1:8189", "127.0.0.1:8189", "", "file:///etc/passwd"]
)
def test_the_bridge_address_must_be_an_http_address(url: str) -> None:
    with pytest.raises(NeedsOwnerError, match="CLI_BRIDGE_URL"):
        ClaudeCliLLM(mode="subscription", bridge_url=url)


def adapters(mode: str, *, confirmed: bool = False, **settings: Any) -> Adapters:
    built = Settings(
        database_url="postgresql+psycopg://vfs:secret@db:5432/vfs", provider_mode=mode, **settings
    )
    return Adapters(built, paid_apis_confirmed=confirmed)


def test_fr27_subscription_mode_plans_with_claude_and_reviews_with_codex() -> None:
    chosen = adapters(
        "subscription",
        cli_bridge_url="http://127.0.0.1:9001",
        claude_cli_model="claude-opus-5-5",
        codex_cli_model="gpt-5.5",
    )

    planner, reviewer = chosen.llm(), chosen.second_opinion()

    assert isinstance(planner, ClaudeCliLLM)
    assert isinstance(reviewer, CodexCliLLM)
    assert (planner.bridge_url, planner.model) == ("http://127.0.0.1:9001", "claude-opus-5-5")
    assert (reviewer.bridge_url, reviewer.model) == ("http://127.0.0.1:9001", "gpt-5.5")


def test_fr28_subscription_mode_never_reaches_for_the_paid_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "planted value, not a real key")

    chosen = adapters("subscription", confirmed=True)

    assert isinstance(chosen.llm(), ClaudeCliLLM)
    assert isinstance(chosen.second_opinion(), CodexCliLLM)


def test_demo_mode_reviews_with_recordings_too() -> None:
    assert isinstance(adapters("demo").second_opinion(), RecordedLLM)


def test_api_mode_has_no_second_reviewer_yet_and_says_so() -> None:
    with pytest.raises(NeedsOwnerError, match="second review"):
        adapters("api", confirmed=True).second_opinion()


# --- Logs ----------------------------------------------------------------------------------


@pytest.fixture
def logged() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    root = logging.getLogger()
    before, level = root.handlers[:], root.level
    logs.configure_logging("debug", stream=stream)
    yield stream
    root.handlers[:] = before
    root.setLevel(level)


def test_nfr01_a_call_is_logged_with_its_numbers_and_without_its_text(
    logged: io.StringIO,
) -> None:
    with stub(200, {**OK, "text": "A secret answer.", "model": "claude-opus-5-5"}) as (url, _):
        claude(url).complete(ask("A secret idea about habits.", system="You plan short videos."))

    lines = [json.loads(line) for line in logged.getvalue().splitlines()]
    (call,) = [line for line in lines if line["message"] == "model call"]
    assert call["provider"] == "claude_plan"
    assert call["model"] == "claude-opus-5-5"
    assert (call["skill"], call["skill_version"]) == ("brief", "1")
    assert (call["input_tokens"], call["output_tokens"]) == (10, 2)
    assert call["cost_usd"] == "0"
    everything = logged.getvalue()
    assert "A secret idea" not in everything
    assert "You plan short videos." not in everything
    assert "A secret answer." not in everything
