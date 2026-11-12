"""Do the installed `claude` and `codex` programs accept every flag the bridge passes?

Section 3.4: "Confirm every flag against the installed versions". The tools update
themselves, so this check can be repeated at any time with `make bridge-flags`.

No model call is made and no plan usage is spent: each tool is started with the bridge's
full command line and an empty prompt. A tool reads its options first, so an option it
does not know is reported as such, and when all are known it stops at the missing prompt.

These tests need the real tools, so they are left out of the normal test run and of CI.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from tools.cli_bridge import claude, codex
from tools.cli_bridge.config import BridgeConfig
from tools.cli_bridge.contract import ClaudeRequest, CodexRequest
from tools.cli_bridge.environment import child_environment
from tools.cli_bridge.process import Finished, resolve, run

pytestmark = pytest.mark.host_tools

SCHEMA = {
    "type": "object",
    "properties": {"lesson": {"type": "string", "description": 'With "quotes" and a \\.'}},
    "required": ["lesson"],
    "additionalProperties": False,
}
CONFIG = BridgeConfig.from_environment(os.environ)


def start_without_a_prompt(command: tuple[str, ...], build: object) -> Finished:
    program = resolve(command)
    if program is None:
        pytest.skip(f"{command[0]} is not installed on this PC")
    with tempfile.TemporaryDirectory(prefix="vf-bridge-") as folder:
        work, inputs = Path(folder, "work"), Path(folder, "input")
        work.mkdir()
        inputs.mkdir()
        arguments = build(work, inputs)  # type: ignore[operator]
        return run(
            [*program, *arguments],
            stdin="",
            env=child_environment(os.environ),
            cwd=work,
            timeout_s=60,
        )


@pytest.mark.parametrize(
    "request_",
    [
        ClaudeRequest(prompt="unused"),
        ClaudeRequest(prompt="unused", web_search=True),
        ClaudeRequest(
            prompt="unused",
            system="You plan short videos.",
            schema=SCHEMA,
            model="sonnet",
            effort="low",
            max_turns=2,
        ),
    ],
    ids=["plain", "research", "everything"],
)
def test_claude_accepts_every_flag_the_bridge_passes(request_: ClaudeRequest) -> None:
    finished = start_without_a_prompt(
        CONFIG.claude_command, lambda work, inputs: claude.arguments(request_, inputs=inputs)
    )

    said = finished.stdout + finished.stderr
    assert "unknown option" not in said, said
    assert "Input must be provided" in said, said


@pytest.mark.parametrize(
    "request_",
    [
        CodexRequest(prompt="unused"),
        CodexRequest(prompt="unused", system="Be strict.", schema=SCHEMA, effort="low"),
    ],
    ids=["plain", "everything"],
)
def test_codex_accepts_every_flag_the_bridge_passes(request_: CodexRequest) -> None:
    finished = start_without_a_prompt(
        CONFIG.codex_command,
        lambda work, inputs: codex.arguments(request_, work=work, inputs=inputs),
    )

    said = finished.stdout + finished.stderr
    assert "No prompt provided" in said, said


def test_claude_reports_its_sign_in_in_the_form_the_bridge_reads() -> None:
    finished = start_without_a_prompt(
        CONFIG.claude_command, lambda work, inputs: list(claude.STATUS_ARGUMENTS)
    )

    signed_in, billing, _ = claude.sign_in(finished)
    assert '"loggedIn"' in finished.stdout
    assert (signed_in, billing) in {(True, "plan"), (True, "api"), (False, None)}


def test_codex_reports_its_sign_in_in_the_form_the_bridge_reads() -> None:
    finished = start_without_a_prompt(
        CONFIG.codex_command, lambda work, inputs: list(codex.STATUS_ARGUMENTS)
    )

    said = finished.stdout + finished.stderr
    assert "Logged in using" in said or "Not logged in" in said, "an unknown status wording"
