"""Run, start, stop and look at the bridge.

    python -m tools.cli_bridge run      in the foreground, log on the screen
    python -m tools.cli_bridge start    in the background, next to the stack (make up)
    python -m tools.cli_bridge stop     end the one in the background (make down)
    python -m tools.cli_bridge status   is it running, and is each tool ready

`stop` and `start` find a running bridge by asking the port, not through a file with a
process number: what answers there says itself whether it is the bridge. Anything else on
the port is left alone.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

from packages.core.logs import configure_logging
from tools.cli_bridge.config import ROOT, BridgeConfig, ConfigError
from tools.cli_bridge.process import detached
from tools.cli_bridge.server import HOST, make_server
from tools.cli_bridge.service import SERVICE, Bridge

log = logging.getLogger(__name__)

START_SECONDS = 30
STOP_SECONDS = 15


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.cli_bridge",
        description="Host bridge to the Claude Code and Codex command line tools.",
    )
    parser.add_argument(
        "command", nargs="?", default="run", choices=("run", "start", "stop", "status")
    )
    chosen = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    try:
        config = BridgeConfig.from_environment(environ)
    except ConfigError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    commands = {"run": _run, "start": _start, "stop": _stop, "status": _status}
    return commands[chosen.command](config, environ)


def _say(text: str) -> None:
    sys.stdout.write(f"{text}\n")
    sys.stdout.flush()


def _address(config: BridgeConfig) -> str:
    return f"http://{HOST}:{config.port}"


def _port_is_free(port: int) -> bool:
    """Whether nothing listens on the port.

    Taking the port for a moment answers at once. Asking a closed port does not: Windows
    waits two seconds before it reports that nobody is there.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def _probe(config: BridgeConfig) -> tuple[str, dict[str, Any]]:
    """What answers on the bridge's port: "bridge" with its health, "other", or "nothing"."""
    if _port_is_free(config.port):
        return ("nothing", {})
    connection = http.client.HTTPConnection(HOST, config.port, timeout=30)
    try:
        connection.request("GET", "/health")
        answer = json.loads(connection.getresponse().read())
    except ConnectionRefusedError:
        return ("nothing", {})
    except (OSError, ValueError, http.client.HTTPException):
        return ("other", {})
    finally:
        connection.close()
    if isinstance(answer, dict) and answer.get("service") == SERVICE:
        return ("bridge", answer)
    return ("other", {})


def _other(config: BridgeConfig) -> int:
    _say(
        f"Port {config.port} is in use by a program that is not the bridge. It was left "
        f"alone. Free the port, or set CLI_BRIDGE_PORT and CLI_BRIDGE_URL to another one."
    )
    return 1


def _run(config: BridgeConfig, environ: Mapping[str, str]) -> int:
    configure_logging("info")
    try:
        server = make_server(Bridge(config, environ=environ), port=config.port)
    except OSError as error:
        sys.stderr.write(f"The bridge could not listen on {_address(config)}: {error}\n")
        return 1
    log.info("bridge listening", extra={"port": config.port, "pid": os.getpid()})
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    server.server_close()
    return 0


def _start(config: BridgeConfig, environ: Mapping[str, str]) -> int:
    state, _ = _probe(config)
    if state == "bridge":
        _say(f"The bridge is already running at {_address(config)}.")
        return 0
    if state == "other":
        return _other(config)
    config.log_file.parent.mkdir(parents=True, exist_ok=True)
    with config.log_file.open("wb") as log_file:
        # The bridge outlives this command: nothing waits for it, `stop` ends it.
        process = subprocess.Popen(
            [sys.executable, "-m", "tools.cli_bridge", "run"],
            cwd=ROOT,
            env=dict(environ),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            shell=False,
            **detached(),
        )
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        state, health = _probe(config)
        if state == "bridge":
            _say(f"The bridge is running at {_address(config)}. Log: {config.log_file}")
            _say_tools(health)
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.2)
    _say(f"The bridge did not start. See {config.log_file}")
    return 1


def _stop(config: BridgeConfig, environ: Mapping[str, str]) -> int:
    state, health = _probe(config)
    if state == "nothing":
        _say("The bridge is not running.")
        return 0
    if state == "other" or not isinstance(health.get("pid"), int):
        return _other(config)
    with contextlib.suppress(OSError):
        os.kill(health["pid"], signal.SIGTERM)
    deadline = time.monotonic() + STOP_SECONDS
    while time.monotonic() < deadline:
        if _probe(config)[0] == "nothing":
            _say("The bridge is stopped.")
            return 0
        time.sleep(0.2)
    _say(f"The bridge at {_address(config)} did not stop.")
    return 1


def _status(config: BridgeConfig, environ: Mapping[str, str]) -> int:
    state, health = _probe(config)
    if state == "nothing":
        _say("The bridge is not running. Start it with: make bridge-start")
        return 1
    if state == "other":
        return _other(config)
    _say(f"The bridge is running at {_address(config)}.")
    _say_tools(health)
    return 0


def _say_tools(health: Mapping[str, Any]) -> None:
    tools = health.get("tools")
    for name, status in tools.items() if isinstance(tools, dict) else ():
        if status.get("ready"):
            plan = f", plan {status['plan']}" if status.get("plan") else ""
            _say(f"  {name}: ready (version {status.get('version')}{plan})")
        else:
            _say(f"  {name}: not ready. {status.get('message')}")
