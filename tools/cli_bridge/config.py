"""Settings of the bridge. All are optional and come from environment variables.

There is no setting for the address the bridge listens on. It is 127.0.0.1, always
(design doc section 3.4, NFR-02).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PORT = 8189


class ConfigError(Exception):
    """A setting has a value the bridge cannot start with."""


@dataclass(frozen=True)
class BridgeConfig:
    # The program of each tool, as a name on the PATH or a full path. Tests put a fake
    # program with its own arguments here.
    claude_command: tuple[str, ...] = ("claude",)
    codex_command: tuple[str, ...] = ("codex",)
    port: int = DEFAULT_PORT
    # How long one model call may take when the request does not say, and at most.
    timeout_seconds: float = 600.0
    max_timeout_seconds: float = 1800.0
    # How long a request waits for its turn while the same tool is busy.
    queue_seconds: float = 600.0
    # How long `claude auth status` or `codex login status` may take.
    status_timeout_seconds: float = 20.0
    # Where a bridge started in the background writes its log.
    log_file: Path = ROOT / ".run" / "cli-bridge.log"

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> BridgeConfig:
        timeout = _seconds(environ, "CLI_BRIDGE_TIMEOUT_SECONDS", cls.timeout_seconds)
        return cls(
            claude_command=(environ.get("CLAUDE_BIN") or "claude",),
            codex_command=(environ.get("CODEX_BIN") or "codex",),
            port=_port(environ),
            timeout_seconds=timeout,
            max_timeout_seconds=max(cls.max_timeout_seconds, timeout),
            queue_seconds=_seconds(environ, "CLI_BRIDGE_QUEUE_SECONDS", cls.queue_seconds),
            log_file=Path(environ.get("CLI_BRIDGE_LOG") or cls.log_file),
        )


def _port(environ: Mapping[str, str]) -> int:
    text = environ.get("CLI_BRIDGE_PORT") or str(DEFAULT_PORT)
    if not text.isdecimal() or not 1 <= int(text) <= 65535:
        raise ConfigError(f"CLI_BRIDGE_PORT must be a port number from 1 to 65535, not {text!r}.")
    return int(text)


def _seconds(environ: Mapping[str, str], name: str, default: float) -> float:
    text = environ.get(name)
    if not text:
        return default
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{name} must be a number of seconds above 0, not {text!r}.")
    return value
