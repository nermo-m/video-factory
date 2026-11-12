"""`GET /health`: is each tool installed and signed in with a plan (section 3.4)."""

from __future__ import annotations

import ast
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from tools.cli_bridge.contract import ClaudeRequest
from tools.cli_bridge.tests.support import MISSING, PLANTED, bridge, calls, fake, only

PACKAGE = Path(__file__).resolve().parents[1]


def test_both_tools_ready() -> None:
    health = bridge(claude=fake("claude"), codex=fake("codex")).health()

    assert health["tools"]["claude"]["ready"] is True
    assert health["tools"]["codex"]["ready"] is True
    assert health["tools"]["claude"]["version"] == "2.1.300"
    assert health["tools"]["codex"]["version"] == "0.144.1"


@pytest.mark.parametrize(
    ("tool", "login"), [("claude", "claude auth login"), ("codex", "codex login")]
)
def test_a_signed_out_tool_is_installed_but_not_ready(tool: str, login: str) -> None:
    health = only(tool, fake(tool, sign_in="none")).health()

    status = health["tools"][tool]
    assert (status["installed"], status["signed_in"], status["ready"]) == (True, False, False)
    assert status["billing"] is None
    assert login in status["message"]


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_fr28_an_api_key_sign_in_is_never_ready(tool: str) -> None:
    health = only(tool, fake(tool, sign_in="api")).health()

    status = health["tools"][tool]
    assert (status["signed_in"], status["billing"], status["ready"]) == (True, "api", False)
    assert "plan" in status["message"]


def test_the_codex_key_hint_is_not_passed_on() -> None:
    health = bridge(codex=fake("codex", sign_in="api")).health()

    assert "sk-proj" not in json.dumps(health)


def test_a_missing_tool_is_not_installed() -> None:
    status = bridge(claude=MISSING).health()["tools"]["claude"]

    assert (status["installed"], status["signed_in"], status["ready"]) == (False, False, False)
    assert status["version"] is None


def test_a_status_check_that_hangs_does_not_hang_the_bridge() -> None:
    studio = bridge(claude=fake("claude", status_sleep=30), status_timeout_seconds=0.5)
    started = time.monotonic()

    status = studio.health()["tools"]["claude"]

    assert time.monotonic() - started < 15
    assert (status["installed"], status["ready"]) == (True, False)
    assert "did not answer" in status["message"]


def test_fr27_the_status_checks_run_without_key_variables(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    environ = {**os.environ, "ANTHROPIC_API_KEY": PLANTED, "OPENAI_API_KEY": PLANTED}

    bridge(
        claude=fake("claude", record=record), codex=fake("codex", record=record), environ=environ
    ).health()

    asked = calls(record, "status") + calls(record, "version")
    assert len(asked) == 4
    assert all(PLANTED not in json.dumps(call["env"]) for call in asked)


def test_the_status_commands_are_the_documented_ones(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"

    bridge(claude=fake("claude", record=record), codex=fake("codex", record=record)).health()

    asked = sorted(call["argv"] for call in calls(record, "status"))
    assert asked == [["auth", "status", "--json"], ["login", "status"]]


def test_health_shows_a_tool_that_is_in_the_middle_of_a_call(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    studio = bridge(claude=fake("claude", output="claude_text.json", record=record, sleep=2))
    call = threading.Thread(target=lambda: studio.claude(ClaudeRequest(prompt="An idea.")))
    call.start()
    deadline = time.monotonic() + 15
    while not calls(record) and time.monotonic() < deadline:
        time.sleep(0.05)

    busy = studio.health()["tools"]["claude"]["busy"]
    call.join(timeout=30)

    assert busy is True
    assert studio.health()["tools"]["claude"]["busy"] is False


def sources() -> list[Path]:
    return sorted(path for path in PACKAGE.glob("*.py"))


def test_the_bridge_needs_nothing_but_python() -> None:
    """It runs on the host, outside the containers, so it must not need their packages."""
    allowed = set(sys.stdlib_module_names) | {"tools", "packages"}
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in allowed, f"{path.name} imports {name}"
                if name.startswith("packages"):
                    # The shared log format is plain Python and pulls in nothing else.
                    assert name == "packages.core" or name.startswith("packages.core.logs"), (
                        f"{path.name} imports {name}"
                    )


def test_the_bridge_never_names_a_credential_file() -> None:
    """Section 3.4: "The app never reads, copies or logs the tools' credential files"."""
    forbidden = (".credentials", "credentials.json", "auth.json", ".claude", ".codex", "keychain")
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        documentation = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in documentation:
                    continue
                lowered = node.value.lower()
                assert not any(word in lowered for word in forbidden), (
                    f"{path.name} line {node.lineno} names {node.value!r}"
                )


def test_the_tools_are_started_without_a_shell() -> None:
    """Arguments go to the tool as a list. A shell would read them a second time."""
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = ast.unparse(node.func)
            assert called not in {"os.system", "os.popen"}, f"{path.name} calls {called}"
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    assert ast.unparse(keyword.value) == "False", f"{path.name} uses a shell"
