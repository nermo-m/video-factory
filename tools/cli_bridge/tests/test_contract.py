"""What a request to the bridge may contain. Everything else is refused before a tool starts."""

from __future__ import annotations

from typing import Any

import pytest

from tools.cli_bridge.contract import (
    ClaudeRequest,
    CodexRequest,
    parse_claude_request,
    parse_codex_request,
)
from tools.cli_bridge.errors import BridgeError

LIMITS = {"max_timeout_seconds": 1800.0}


def refused(parse: Any, body: Any) -> str:
    with pytest.raises(BridgeError) as raised:
        parse(body, **LIMITS)
    assert raised.value.code == "bad_request"
    assert raised.value.status == 400
    return raised.value.message


def test_the_smallest_request_is_a_prompt() -> None:
    assert parse_claude_request({"prompt": "Hello"}, **LIMITS) == ClaudeRequest(prompt="Hello")
    assert parse_codex_request({"prompt": "Hello"}, **LIMITS) == CodexRequest(prompt="Hello")


def test_every_field_of_a_claude_request_is_read() -> None:
    request = parse_claude_request(
        {
            "prompt": "Hello",
            "system": "Be brief.",
            "schema": {"type": "object"},
            "model": "claude-opus-5-5",
            "effort": "high",
            "web_search": True,
            "max_turns": 6,
            "timeout_s": 120,
        },
        **LIMITS,
    )

    assert request == ClaudeRequest(
        prompt="Hello",
        system="Be brief.",
        schema={"type": "object"},
        model="claude-opus-5-5",
        effort="high",
        web_search=True,
        max_turns=6,
        timeout_s=120.0,
    )


def test_every_field_of_a_codex_request_is_read() -> None:
    request = parse_codex_request(
        {
            "prompt": "Hello",
            "system": "Be strict.",
            "schema": {"type": "object"},
            "model": "gpt-5.5",
            "effort": "low",
            "timeout_s": 60.5,
        },
        **LIMITS,
    )

    assert request == CodexRequest(
        prompt="Hello",
        system="Be strict.",
        schema={"type": "object"},
        model="gpt-5.5",
        effort="low",
        timeout_s=60.5,
    )


@pytest.mark.parametrize("parse", [parse_claude_request, parse_codex_request])
@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "prompt",
        {},
        {"prompt": ""},
        {"prompt": "   \n"},
        {"prompt": 7},
        {"prompt": "Hello", "system": 7},
        {"prompt": "Hello", "schema": "not an object"},
        {"prompt": "Hello", "schema": []},
        {"prompt": "Hello", "model": ""},
        {"prompt": "Hello", "model": 5},
        {"prompt": "Hello", "effort": "enormous"},
        {"prompt": "Hello", "timeout_s": 0},
        {"prompt": "Hello", "timeout_s": -5},
        {"prompt": "Hello", "timeout_s": "soon"},
        {"prompt": "Hello", "timeout_s": True},
        {"prompt": "Hello", "timeout_s": 1801},
        {"prompt": "Hello", "surprise": 1},
    ],
)
def test_a_malformed_request_is_refused(parse: Any, body: Any) -> None:
    refused(parse, body)


@pytest.mark.parametrize("parse", [parse_claude_request, parse_codex_request])
@pytest.mark.parametrize(
    "model",
    [
        "--dangerously-skip-permissions",
        "-m",
        "opus --bare",
        "opus\n--bare",
        'gpt-5" -c shell_tool=true',
        "a" * 200,
    ],
)
def test_a_model_name_cannot_smuggle_in_an_option(parse: Any, model: str) -> None:
    message = refused(parse, {"prompt": "Hello", "model": model})

    assert "model" in message


@pytest.mark.parametrize(
    "body",
    [
        {"prompt": "Hello", "web_search": "yes"},
        {"prompt": "Hello", "max_turns": 0},
        {"prompt": "Hello", "max_turns": 51},
        {"prompt": "Hello", "max_turns": 2.5},
        {"prompt": "Hello", "max_turns": True},
    ],
)
def test_a_malformed_claude_field_is_refused(body: Any) -> None:
    refused(parse_claude_request, body)


@pytest.mark.parametrize("field", ["web_search", "max_turns"])
def test_codex_has_no_search_and_no_turn_count(field: str) -> None:
    message = refused(parse_codex_request, {"prompt": "Hello", field: 1})

    assert field in message


def test_codex_efforts_are_the_three_this_bridge_has_checked() -> None:
    for effort in ("low", "medium", "high"):
        assert parse_codex_request({"prompt": "x", "effort": effort}, **LIMITS).effort == effort
    refused(parse_codex_request, {"prompt": "x", "effort": "max"})


def test_a_schema_too_large_for_a_command_line_is_refused() -> None:
    huge = {"type": "object", "description": "x" * 30_000}

    message = refused(parse_claude_request, {"prompt": "Hello", "schema": huge})

    assert "schema" in message


def test_the_message_names_the_field_and_never_repeats_the_prompt() -> None:
    message = refused(
        parse_claude_request, {"prompt": "A secret idea about habits.", "effort": "enormous"}
    )

    assert "effort" in message
    assert "secret idea" not in message
