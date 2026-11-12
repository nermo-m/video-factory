"""Starting and stopping the bridge next to the stack (`make up`, `make down`).

These tests start a real bridge process on a free port. The tools it would run are set to
names that do not exist, so nothing but the bridge itself is started.
"""

from __future__ import annotations

import http.client
import http.server
import json
import os
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tools.cli_bridge.cli import main
from tools.cli_bridge.config import BridgeConfig, ConfigError
from tools.cli_bridge.tests.support import PLANTED


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def health(port: int) -> dict[str, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("GET", "/health")
    body: dict[str, Any] = json.loads(connection.getresponse().read())
    connection.close()
    return body


@pytest.fixture
def environ(tmp_path: Path) -> Iterator[dict[str, str]]:
    settings = {
        **os.environ,
        "CLI_BRIDGE_PORT": str(free_port()),
        "CLI_BRIDGE_LOG": str(tmp_path / "logs" / "bridge.log"),
        "CLAUDE_BIN": "no-such-claude-for-the-bridge-tests",
        "CODEX_BIN": "no-such-codex-for-the-bridge-tests",
        "ANTHROPIC_API_KEY": PLANTED,
    }
    yield settings
    main(["stop"], environ=settings)


def test_start_launches_the_bridge_and_stop_ends_it(
    environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    port = int(environ["CLI_BRIDGE_PORT"])

    assert main(["start"], environ=environ) == 0
    assert f"http://127.0.0.1:{port}" in capsys.readouterr().out
    assert health(port)["service"] == "cli-bridge"

    assert main(["status"], environ=environ) == 0
    assert "running" in capsys.readouterr().out

    assert main(["stop"], environ=environ) == 0
    assert "stopped" in capsys.readouterr().out

    assert main(["status"], environ=environ) == 1
    assert "not running" in capsys.readouterr().out


def test_starting_twice_keeps_the_one_that_runs(
    environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    port = int(environ["CLI_BRIDGE_PORT"])
    assert main(["start"], environ=environ) == 0
    first = health(port)["pid"]

    assert main(["start"], environ=environ) == 0

    assert "already running" in capsys.readouterr().out
    assert health(port)["pid"] == first


def test_stopping_what_is_not_running_is_not_an_error(
    environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["stop"], environ=environ) == 0
    assert "not running" in capsys.readouterr().out


def test_status_names_what_each_tool_needs(
    environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["start"], environ=environ)
    capsys.readouterr()

    main(["status"], environ=environ)

    out = capsys.readouterr().out
    assert "claude" in out
    assert "CLAUDE_BIN" in out
    assert "codex" in out


def test_nfr01_the_log_of_a_started_bridge_is_json_without_secrets(
    environ: dict[str, str],
) -> None:
    main(["start"], environ=environ)
    health(int(environ["CLI_BRIDGE_PORT"]))
    main(["stop"], environ=environ)

    text = Path(environ["CLI_BRIDGE_LOG"]).read_text(encoding="utf-8")
    lines = [json.loads(line) for line in text.splitlines()]
    assert any(line["message"] == "bridge listening" for line in lines)
    assert PLANTED not in text


class _Other(http.server.BaseHTTPRequestHandler):
    """Something that is not the bridge, on the bridge's port."""

    def do_GET(self) -> None:
        body = json.dumps({"service": "something-else", "pid": 4}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


@pytest.fixture
def occupied(environ: dict[str, str]) -> Iterator[dict[str, str]]:
    port = int(environ["CLI_BRIDGE_PORT"])
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Other)
    # The short interval is how often the server looks whether it was told to stop.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    yield environ
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)


def test_stop_leaves_another_program_on_the_port_alone(
    occupied: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["stop"], environ=occupied) == 1

    assert "not the bridge" in capsys.readouterr().out
    assert health(int(occupied["CLI_BRIDGE_PORT"]))["service"] == "something-else"


def test_start_says_when_the_port_is_taken(
    occupied: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["start"], environ=occupied) == 1

    assert "not the bridge" in capsys.readouterr().out


def test_settings_come_from_the_environment_with_defaults() -> None:
    defaults = BridgeConfig.from_environment({})
    chosen = BridgeConfig.from_environment(
        {
            "CLI_BRIDGE_PORT": "9001",
            "CLAUDE_BIN": "C:\\Tools\\claude.exe",
            "CODEX_BIN": "/opt/codex/bin/codex",
            "CLI_BRIDGE_TIMEOUT_SECONDS": "90",
            "CLI_BRIDGE_QUEUE_SECONDS": "5",
        }
    )

    assert defaults.port == 8189
    assert defaults.claude_command == ("claude",)
    assert defaults.codex_command == ("codex",)
    assert defaults.timeout_seconds == 600
    assert (chosen.port, chosen.timeout_seconds, chosen.queue_seconds) == (9001, 90, 5)
    assert chosen.claude_command == ("C:\\Tools\\claude.exe",)
    assert chosen.codex_command == ("/opt/codex/bin/codex",)


@pytest.mark.parametrize(
    "settings",
    [
        {"CLI_BRIDGE_PORT": "eighty"},
        {"CLI_BRIDGE_PORT": "0"},
        {"CLI_BRIDGE_PORT": "70000"},
        {"CLI_BRIDGE_TIMEOUT_SECONDS": "-1"},
        {"CLI_BRIDGE_TIMEOUT_SECONDS": "soon"},
        {"CLI_BRIDGE_QUEUE_SECONDS": "nan"},
    ],
)
def test_a_setting_that_makes_no_sense_stops_the_start(settings: dict[str, str]) -> None:
    with pytest.raises(ConfigError) as raised:
        BridgeConfig.from_environment(settings)

    assert next(iter(settings)) in str(raised.value)


def test_a_bad_setting_is_reported_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["status"], environ={"CLI_BRIDGE_PORT": "eighty"}) == 2

    assert "CLI_BRIDGE_PORT" in capsys.readouterr().err
