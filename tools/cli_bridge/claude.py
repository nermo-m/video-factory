"""The Claude Code command line tool: what the bridge passes to it and how it reads it.

Every flag here was confirmed against Claude Code 2.1.300 (ADR 8). `make bridge-flags`
checks them again against the installed version without making a model call.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.cli_bridge.answers import count, json_object
from tools.cli_bridge.contract import ClaudeRequest, compact
from tools.cli_bridge.errors import (
    INVALID_OUTPUT,
    NOT_PLAN_SIGN_IN,
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
# Characters of a page or search summary that are passed on with a source.
MAX_SOURCE_TEXT = 4000

ALWAYS = (
    "-p",
    # Every message of the run, one JSON object per line. The last one is the result. The
    # ones before it say which model the session uses, whether an API key was used, which
    # pages a search returned and how much of the plan is used. The single-result form
    # holds none of that.
    "--output-format",
    "stream-json",
    "--verbose",
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
    events = _events(finished.stdout)
    result = _last(events, "result")
    session = _last(events, "system") or {}
    key_source = session.get("apiKeySource")
    if isinstance(key_source, str) and key_source != "none":
        # The sign-in check before the call should have stopped this. If a key was used
        # all the same, the call must not be counted as covered by the plan.
        raise BridgeError(
            NOT_PLAN_SIGN_IN,
            f"Claude Code used an API key for this call ({brief(key_source, 60)}), not the "
            "plan. Remove the key from the tool's settings and sign in with your plan.",
            status=503,
            tool=NAME,
        )
    limits = _last(events, "rate_limit_event") or {}
    report = limits.get("rate_limit_info")
    report = report if isinstance(report, dict) else {}
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
        failure = _failure(f"{text}\n{finished.stderr}", finished, now)
        resets = report.get("resetsAt")
        if failure.code == PLAN_LIMIT and report.get("status") == "rejected" and count(resets):
            # The tool's own number, which does not depend on reading its sentence.
            failure.retry_at = datetime.fromtimestamp(count(resets), UTC)
        raise failure

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
    sources, searches = _sources(events)
    return {
        "tool": NAME,
        "output": output,
        "text": text,
        "model": _session_model(session) or _model(result.get("modelUsage")),
        "usage": {
            # Everything the model read: new input, and what was written to or read from
            # the cache.
            "input_tokens": count(usage.get("input_tokens")) + cached + written,
            "cached_input_tokens": cached,
            "output_tokens": count(usage.get("output_tokens")),
        },
        "searches": searches,
        # The pages a search returned or a fetch read, for checking claims (FR-02).
        "sources": sources,
        # Reported by the tool, not counted by this app. None when it reported nothing.
        "plan_usage": _plan_usage(report),
        "turns": count(result.get("num_turns")),
        "tool_duration_ms": count(result.get("duration_ms")),
    }


def _events(stdout: str) -> list[dict[str, Any]]:
    """The messages the tool printed: one JSON object per line.

    Older versions and the single-result form print one JSON document, or a list of them.
    Those are read too.
    """
    try:
        whole = json.loads(stdout)
    except ValueError:
        whole = None
    if isinstance(whole, dict):
        return [whole]
    if isinstance(whole, list):
        return [event for event in whole if isinstance(event, dict)]
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _last(events: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    return next((event for event in reversed(events) if event.get("type") == kind), None)


def _session_model(session: dict[str, Any]) -> str | None:
    model = session.get("model")
    return model if isinstance(model, str) and model else None


def _sources(events: list[dict[str, Any]]) -> tuple[list[dict[str, str]], int]:
    """The pages the tools brought back, and how many searches were made.

    A search result holds a list of links and, after it, what the search said about them.
    A fetch result holds one address and what was read from that page.
    """
    sources: dict[str, dict[str, str]] = {}
    searches = 0
    for event in events:
        outcome = event.get("tool_use_result")
        if not isinstance(outcome, dict):
            continue
        results = outcome.get("results")
        if isinstance(results, list):
            searches += count(outcome.get("searchCount")) or 1
            said = " ".join(item for item in results if isinstance(item, str))
            for item in results:
                links = item.get("content") if isinstance(item, dict) else None
                for link in links if isinstance(links, list) else []:
                    if isinstance(link, dict) and isinstance(link.get("url"), str):
                        sources.setdefault(
                            link["url"],
                            {
                                "url": link["url"],
                                "title": str(link.get("title") or ""),
                                "text": said[:MAX_SOURCE_TEXT],
                            },
                        )
        elif isinstance(outcome.get("url"), str) and isinstance(outcome.get("result"), str):
            # What was read from the page itself is better than a search's summary of it.
            sources[outcome["url"]] = {
                "url": outcome["url"],
                "title": sources.get(outcome["url"], {}).get("title", ""),
                "text": outcome["result"][:MAX_SOURCE_TEXT],
            }
    return list(sources.values()), searches


def _plan_usage(report: dict[str, Any]) -> dict[str, Any] | None:
    """How much of each window of the plan is used, as the tool reports it."""
    windows = report.get("unifiedWindows")
    if not isinstance(windows, dict):
        return None
    usage = {}
    for name, window in windows.items():
        if not isinstance(window, dict) or not isinstance(window.get("utilization"), int | float):
            continue
        resets = count(window.get("resetsAt"))
        usage[str(name)] = {
            "used": float(window["utilization"]),
            "resets_at": datetime.fromtimestamp(resets, UTC).isoformat() if resets else None,
        }
    return usage or None


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
