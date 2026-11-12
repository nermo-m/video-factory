"""What a request to the bridge may contain.

A request is checked in full before a tool is started. Unknown fields are refused, so a
caller that expects a feature this bridge does not have finds out at once.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tools.cli_bridge.errors import bad_request

CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
# The Codex tool does not check this value itself, so only values known to work are let in.
CODEX_EFFORTS = ("low", "medium", "high")
MAX_TURNS = 50
MAX_PROMPT_CHARACTERS = 1_000_000
MAX_SYSTEM_CHARACTERS = 200_000
# The Claude schema travels on the command line, which Windows limits to 32,767
# characters in total. The limit here is on the schema as it is written there, with its
# quotes escaped, and leaves room for the program path and the other arguments. It is
# the same on every system, so a request behaves the same in CI and on the owner's PC.
MAX_CLAUDE_SCHEMA_CHARACTERS = 24_000
# The Codex schema travels in a file.
MAX_CODEX_SCHEMA_CHARACTERS = 200_000
# A model name starts with a letter or digit, so it can never be read as an option.
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,79}")


@dataclass(frozen=True)
class ClaudeRequest:
    prompt: str
    system: str | None = None
    schema: Mapping[str, Any] | None = None
    model: str | None = None
    effort: str | None = None
    web_search: bool = False
    max_turns: int | None = None
    timeout_s: float | None = None


@dataclass(frozen=True)
class CodexRequest:
    prompt: str
    system: str | None = None
    schema: Mapping[str, Any] | None = None
    model: str | None = None
    effort: str | None = None
    timeout_s: float | None = None


def compact(schema: Mapping[str, Any]) -> str:
    """A schema as the shortest JSON text."""
    return json.dumps(schema, separators=(",", ":"), ensure_ascii=False)


class _Fields:
    """Reads the fields of one request body and says which one is wrong."""

    def __init__(self, body: object, allowed: frozenset[str]) -> None:
        if not isinstance(body, dict):
            raise bad_request("The request body must be a JSON object.")
        unknown = sorted(str(name)[:40] for name in body if name not in allowed)
        if unknown:
            raise bad_request(f"Unknown field: {', '.join(unknown)}.")
        self._body: dict[str, Any] = body

    def text(self, name: str, *, limit: int, required: bool = False) -> str | None:
        value = self._body.get(name)
        if value is None and not required:
            return None
        if not isinstance(value, str):
            raise bad_request(f"`{name}` must be a text.")
        if required and not value.strip():
            raise bad_request(f"`{name}` must not be empty.")
        if len(value) > limit:
            raise bad_request(f"`{name}` is longer than {limit} characters.")
        return value

    def model(self) -> str | None:
        value = self._body.get("model")
        if value is None:
            return None
        if not isinstance(value, str) or _MODEL.fullmatch(value) is None:
            raise bad_request("`model` must be a model name: letters, digits, dots and dashes.")
        return value

    def choice(self, name: str, choices: tuple[str, ...]) -> str | None:
        value = self._body.get(name)
        if value is None:
            return None
        if value not in choices:
            raise bad_request(f"`{name}` must be one of: {', '.join(choices)}.")
        return str(value)

    def flag(self, name: str) -> bool:
        value = self._body.get(name, False)
        if not isinstance(value, bool):
            raise bad_request(f"`{name}` must be true or false.")
        return value

    def whole(self, name: str, *, low: int, high: int) -> int | None:
        value = self._body.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise bad_request(f"`{name}` must be a whole number from {low} to {high}.")
        return value

    def seconds(self, name: str, *, high: float) -> float | None:
        value = self._body.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise bad_request(f"`{name}` must be a number of seconds.")
        if not math.isfinite(value) or not 0 < value <= high:
            raise bad_request(f"`{name}` must be more than 0 and at most {high:g} seconds.")
        return float(value)

    def schema(self, *, limit: int, on_command_line: bool) -> dict[str, Any] | None:
        value = self._body.get("schema")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise bad_request("`schema` must be a JSON Schema object.")
        text = compact(value)
        size = len(subprocess.list2cmdline([text])) if on_command_line else len(text)
        if size > limit:
            raise bad_request(f"`schema` is too large: {size} characters, the limit is {limit}.")
        return value


_COMMON = frozenset({"prompt", "system", "schema", "model", "effort", "timeout_s"})


def parse_claude_request(body: object, *, max_timeout_seconds: float) -> ClaudeRequest:
    fields = _Fields(body, _COMMON | {"web_search", "max_turns"})
    prompt = fields.text("prompt", limit=MAX_PROMPT_CHARACTERS, required=True)
    assert prompt is not None  # noqa: S101 - a required text is never None
    return ClaudeRequest(
        prompt=prompt,
        system=fields.text("system", limit=MAX_SYSTEM_CHARACTERS),
        schema=fields.schema(limit=MAX_CLAUDE_SCHEMA_CHARACTERS, on_command_line=True),
        model=fields.model(),
        effort=fields.choice("effort", CLAUDE_EFFORTS),
        web_search=fields.flag("web_search"),
        max_turns=fields.whole("max_turns", low=1, high=MAX_TURNS),
        timeout_s=fields.seconds("timeout_s", high=max_timeout_seconds),
    )


def parse_codex_request(body: object, *, max_timeout_seconds: float) -> CodexRequest:
    fields = _Fields(body, _COMMON)
    prompt = fields.text("prompt", limit=MAX_PROMPT_CHARACTERS, required=True)
    assert prompt is not None  # noqa: S101 - a required text is never None
    return CodexRequest(
        prompt=prompt,
        system=fields.text("system", limit=MAX_SYSTEM_CHARACTERS),
        schema=fields.schema(limit=MAX_CODEX_SCHEMA_CHARACTERS, on_command_line=False),
        model=fields.model(),
        effort=fields.choice("effort", CODEX_EFFORTS),
        timeout_s=fields.seconds("timeout_s", high=max_timeout_seconds),
    )
