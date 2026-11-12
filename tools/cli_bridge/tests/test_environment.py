"""The environment the bridge gives to the tools it starts (design doc section 3.4, FR-27).

"The bridge removes ANTHROPIC_API_KEY, OPENAI_API_KEY, CODEX_API_KEY and similar variables
from the environment of every command it runs", because `claude -p` uses an API key when
one is present, even when the owner is signed in with a plan.
"""

from __future__ import annotations

import pytest

from tools.cli_bridge.environment import child_environment

BASE = {
    "PATH": "/usr/bin",
    "HOME": "/home/someone",
    "USERPROFILE": "C:\\Users\\someone",
    "APPDATA": "C:\\Users\\someone\\AppData\\Roaming",
    "HTTPS_PROXY": "http://proxy.example:3128",
    "LANG": "en_GB.UTF-8",
}


@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"])
def test_fr27_the_named_key_variables_are_removed(name: str) -> None:
    assert name not in child_environment({**BASE, name: "planted"})


@pytest.mark.parametrize(
    "name",
    [
        # Other ways to point the tools at a paid or different endpoint.
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CODEX_ACCESS_TOKEN",
        "AWS_BEARER_TOKEN_BEDROCK",
        # Keys of other providers have no business in a child either.
        "AZURE_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "SOME_VENDOR_API_KEY_V2",
        # A bridge started from inside a Claude Code session must not hand that session on.
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_SESSION_ID",
    ],
)
def test_fr27_similar_variables_are_removed(name: str) -> None:
    assert name not in child_environment({**BASE, name: "planted"})


def test_fr27_names_are_compared_without_case_as_windows_does() -> None:
    cleaned = child_environment({**BASE, "anthropic_api_key": "planted", "OpenAI_Api_Key": "x"})

    assert set(cleaned) == set(BASE)


@pytest.mark.parametrize(
    "name",
    [
        *BASE,
        # Where the tools keep their own files. The bridge passes the location on and never
        # opens it.
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        # Claude Code on Windows needs this when Git is installed in an unusual place.
        "CLAUDE_CODE_GIT_BASH_PATH",
        "SystemRoot",
        "TEMP",
    ],
)
def test_everything_else_reaches_the_tool(name: str) -> None:
    assert child_environment({**BASE, name: "kept"})[name] == "kept"


def test_the_given_environment_is_not_changed() -> None:
    given = {**BASE, "ANTHROPIC_API_KEY": "planted"}

    child_environment(given)

    assert given["ANTHROPIC_API_KEY"] == "planted"
