"""The Claude Code command line tool: what the bridge passes to it and how it reads it.

Every flag here was confirmed against Claude Code 2.1.300 (ADR 8). `make bridge-flags`
checks them again against the installed version without making a model call.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.cli_bridge.answers import count, json_object
from tools.cli_bridge.contract import ClaudeRequest, compact
from tools.cli_bridge.errors import (
    INVALID_OUTPUT,
    PLAN_LIMIT,
    TOOL_FAILED,
    BridgeError,
    brief,
)
from tools.cli_bridge.limits import find_limit
from tools.cli_bridge.process import Finished

NAME = "claude"
STATUS_ARGUMENTS = ("auth", "status", "--json")
# The sign-in that is billed to a plan. Anything else is billed per use.
PLAN_SIGN_IN = "claude.ai"
SEARCH_TOOLS = "WebSearch,WebFetch"
# A structured answer takes a second turn, and the tool may ask for a correction.
TURNS = 4
SEARCH_TURNS = 16

ALWAYS = (
    "-p",
    "--output-format",
    "json",
    # No CLAUDE.md, skills, plugins, hooks, MCP servers or settings files of the owner.
    "--safe-mode",
    "--setting-sources",
    "",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    # Nobody is there to answer a permission question: what would ask is refused.
    "--permission-prompts",
    "none",
)


def sign_in(finished: Finished) -> tuple[bool, str | None, str | None]:
    """Read `claude auth status --json`: signed in, billing type, and the plan's name.

    The report also names the account. That part is not read.
    """
    try:
        report = json.loads(finished.stdout)
    except ValueError:
        return (False, None, None)
    if not isinstance(report, dict) or report.get("loggedIn") is not True:
        return (False, None, None)
    if report.get("authMethod") != PLAN_SIGN_IN:
        return (True, "api", None)
    plan = report.get("subscriptionType")
    return (True, "plan", plan if isinstance(plan, str) else None)


def arguments(request: ClaudeRequest, *, inputs: Path) -> list[str]:
    """The command line for one call. The prompt is not on it: it goes to standard input."""
    built = list(ALWAYS)
    if request.web_search:
        built += ["--tools", SEARCH_TOOLS, "--allowed-tools", SEARCH_TOOLS]
    else:
        built += ["--tools", ""]
    turns = request.max_turns or (SEARCH_TURNS if request.web_search else TURNS)
    built += ["--max-turns", str(turns)]
    if request.model is not None:
        built += ["--model", request.model]
    if request.effort is not None:
        built += ["--effort", request.effort]
    if request.system:
        file = inputs / "system.txt"
        file.write_text(request.system, encoding="utf-8", newline="")
        built += ["--system-prompt-file", str(file)]
    if request.schema is not None:
        built += ["--json-schema", compact(request.schema)]
    return built


def read(finished: Finished, request: ClaudeRequest, *, now: datetime) -> dict[str, Any]:
    """Turn what the tool printed into the bridge's answer, or raise what went wrong."""
    result = _result(finished.stdout)
    if result is None:
        raise _failure(finished.stderr or finished.stdout, finished, now)
    said = result.get("result")
    text = said if isinstance(said, str) else ""
    failed = (
        result.get("is_error") is True
        or result.get("subtype") != "success"
        or finished.exit_code != 0
    )
    if failed:
        if result.get("subtype") == "error_max_turns":
            turns = count(result.get("num_turns"))
            raise BridgeError(
                TOOL_FAILED,
                f"Claude Code ran out of turns after {turns} without a final answer.",
                status=502,
                tool=NAME,
            )
        raise _failure(f"{text}\n{finished.stderr}", finished, now)

    output = None
    if request.schema is not None:
        structured = result.get("structured_output")
        output = structured if isinstance(structured, dict) else json_object(text)
        if output is None:
            raise BridgeError(
                INVALID_OUTPUT,
                "Claude Code answered without the JSON document the schema asks for.",
                status=502,
                tool=NAME,
            )
    reported = result.get("usage")
    usage: dict[str, Any] = reported if isinstance(reported, dict) else {}
    cached = count(usage.get("cache_read_input_tokens"))
    written = count(usage.get("cache_creation_input_tokens"))
    server_tools = usage.get("server_tool_use")
    searches = server_tools.get("web_search_requests") if isinstance(server_tools, dict) else 0
    return {
        "tool": NAME,
        "output": output,
        "text": text,
        "model": _model(result.get("modelUsage")),
        "usage": {
            # Everything the model read: new input, and what was written to or read from
            # the cache.
            "input_tokens": count(usage.get("input_tokens")) + cached + written,
            "cached_input_tokens": cached,
            "output_tokens": count(usage.get("output_tokens")),
        },
        "searches": count(searches),
        "turns": count(result.get("num_turns")),
        "tool_duration_ms": count(result.get("duration_ms")),
    }


def _result(stdout: str) -> dict[str, Any] | None:
    """The result object in the tool's output, which is one JSON document."""
    try:
        printed = json.loads(stdout)
    except ValueError:
        return None
    # With --verbose the tool prints every message in a list. The result is the last one.
    candidates = printed if isinstance(printed, list) else [printed]
    for candidate in reversed(candidates):
        if isinstance(candidate, dict) and candidate.get("type") == "result":
            return candidate
    return None


def _model(usage: object) -> str | None:
    """The model that wrote the answer. A small helper model may be listed next to it."""
    if not isinstance(usage, dict) or not usage:
        return None
    by_output = {
        str(name): count(numbers.get("outputTokens")) if isinstance(numbers, dict) else 0
        for name, numbers in usage.items()
    }
    return max(by_output, key=lambda name: by_output[name])


def _failure(words: str, finished: Finished, now: datetime) -> BridgeError:
    limit = find_limit(words, now=now)
    if limit is not None:
        return BridgeError(
            PLAN_LIMIT, limit.message, status=429, tool=NAME, retry_at=limit.retry_at
        )
    said = brief(words) or "it printed nothing"
    return BridgeError(
        TOOL_FAILED,
        f"Claude Code failed (exit code {finished.exit_code}): {said}",
        status=502,
        tool=NAME,
    )
