"""The Codex command line tool: what the bridge passes to it and how it reads it.

Every flag here was confirmed against Codex 0.144.1 (ADR 8). `make bridge-flags` checks
them again against the installed version without making a model call.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.cli_bridge.answers import count, json_object
from tools.cli_bridge.contract import CodexRequest, compact
from tools.cli_bridge.errors import (
    INVALID_OUTPUT,
    PLAN_LIMIT,
    TOOL_FAILED,
    BridgeError,
    brief,
)
from tools.cli_bridge.limits import find_limit
from tools.cli_bridge.process import Finished

NAME = "codex"
STATUS_ARGUMENTS = ("login", "status")
# What `codex login status` prints for the sign-in that is billed to a plan.
PLAN_SIGN_IN = "Logged in using ChatGPT"
ANY_SIGN_IN = "Logged in using"

# Everything that lets the model act is switched off: commands, images, apps, plugins,
# other agents, browsers, the desktop, hooks. The tool refuses a name it does not know, so
# a renamed feature stops the call instead of staying switched on.
DISABLED_FEATURES = (
    "shell_tool",
    "image_generation",
    "apps",
    "plugins",
    "remote_plugin",
    "multi_agent",
    "browser_use",
    "browser_use_external",
    "in_app_browser",
    "computer_use",
    "hooks",
    "goals",
    "tool_suggest",
    "skill_mcp_dependency_install",
)

ALWAYS = (
    "exec",
    "--json",
    "--color",
    "never",
    "--skip-git-repo-check",
    # No session file is kept, and nothing of the owner's configuration is read. Sign-in
    # is not part of that configuration and stays as it is.
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    # An option this version does not know is an error, not a warning.
    "--strict-config",
    "--sandbox",
    "read-only",
)


def sign_in(finished: Finished) -> tuple[bool, str | None, str | None]:
    """Read `codex login status`: signed in, billing type. Codex does not name the plan.

    With an API key the line also shows part of the key. That part is not read.
    """
    said = f"{finished.stdout}\n{finished.stderr}"
    if finished.exit_code != 0 or ANY_SIGN_IN not in said:
        return (False, None, None)
    return (True, "plan" if PLAN_SIGN_IN in said else "api", None)


def arguments(request: CodexRequest, *, work: Path, inputs: Path) -> list[str]:
    """The command line for one call. The prompt is not on it: it goes to standard input."""
    built = [*ALWAYS, "--cd", str(work)]
    for feature in DISABLED_FEATURES:
        built += ["--disable", feature]
    built += ["--config", 'web_search="disabled"']
    if request.model is not None:
        built += ["--model", request.model]
    if request.effort is not None:
        built += ["--config", f'model_reasoning_effort="{request.effort}"']
    if request.schema is not None:
        file = inputs / "schema.json"
        file.write_text(compact(request.schema), encoding="utf-8", newline="")
        built += ["--output-schema", str(file)]
    # A single dash: read the prompt from standard input.
    built.append("-")
    return built


def prompt(request: CodexRequest) -> str:
    """Codex has no separate system prompt, so a system text goes in front of the prompt."""
    return f"{request.system}\n\n{request.prompt}" if request.system else request.prompt


def read(finished: Finished, request: CodexRequest, *, now: datetime) -> dict[str, Any]:
    """Turn the events the tool printed into the bridge's answer, or raise what went wrong."""
    messages: list[str] = []
    errors: list[str] = []
    usage: dict[str, Any] = {}
    turns = 0
    turn_failed = False
    for event in _events(finished.stdout):
        kind = event.get("type")
        item = event.get("item")
        if kind == "item.completed" and isinstance(item, dict):
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                messages.append(item["text"])
        elif kind == "turn.completed":
            turns += 1
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
        elif kind == "turn.failed":
            turn_failed = True
            error = event.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                errors.append(error["message"])
        elif kind == "error" and isinstance(event.get("message"), str):
            errors.append(event["message"])

    if finished.exit_code != 0 or turn_failed or not messages:
        words = "\n".join([*errors, finished.stderr])
        limit = find_limit(words, now=now)
        if limit is not None:
            raise BridgeError(
                PLAN_LIMIT, limit.message, status=429, tool=NAME, retry_at=limit.retry_at
            )
        said = brief(errors[-1] if errors else finished.stderr) or "no final message"
        raise BridgeError(
            TOOL_FAILED,
            f"Codex failed (exit code {finished.exit_code}): {said}",
            status=502,
            tool=NAME,
        )

    text = messages[-1]
    output = None
    if request.schema is not None:
        output = json_object(text)
        if output is None:
            raise BridgeError(
                INVALID_OUTPUT,
                "Codex answered without the JSON document the schema asks for.",
                status=502,
                tool=NAME,
            )
    return {
        "tool": NAME,
        "output": output,
        "text": text,
        # The events do not name the model, so this is the one that was asked for, if any.
        "model": request.model,
        "usage": {
            # Codex already counts cached input inside input_tokens.
            "input_tokens": count(usage.get("input_tokens")),
            "cached_input_tokens": count(usage.get("cached_input_tokens")),
            "output_tokens": count(usage.get("output_tokens")),
        },
        "searches": 0,
        "turns": turns,
        "tool_duration_ms": None,
    }


def _events(stdout: str) -> list[dict[str, Any]]:
    """The events of `codex exec --json`, one JSON object per line. Other lines are skipped."""
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events
