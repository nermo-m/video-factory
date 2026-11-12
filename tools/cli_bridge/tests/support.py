"""Shared helpers for the bridge tests: fake tools and a bridge that uses them."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.cli_bridge.config import BridgeConfig
from tools.cli_bridge.service import Bridge

FAKE = Path(__file__).with_name("fake_tool.py")
RECORDED = Path(__file__).with_name("recorded")
# A Thursday, early afternoon, two hours ahead of UTC.
ZONE = timezone(timedelta(hours=2))
NOW = datetime(2026, 11, 12, 13, 0, tzinfo=ZONE)
PLANTED = "planted-key-value-that-must-never-travel"
MISSING = ("no-such-command-for-the-bridge-tests",)


def fake(
    tool: str,
    *,
    output: str | None = None,
    record: Path | None = None,
    sign_in: str = "plan",
    exit_code: int = 0,
    stderr: str = "",
    sleep: float = 0.0,
    status_sleep: float = 0.0,
    image: Path | None = None,
    image_home: Path | None = None,
    announce: bool = False,
) -> tuple[str, ...]:
    """The command line of a fake tool. The bridge appends its own arguments after `--`."""
    command = [sys.executable, str(FAKE), "--tool", tool, "--sign-in", sign_in]
    if output is not None:
        command += ["--output", str(RECORDED / output)]
    if record is not None:
        command += ["--record", str(record)]
    if exit_code:
        command += ["--exit", str(exit_code)]
    if stderr:
        command += ["--stderr", stderr]
    if sleep:
        command += ["--sleep", str(sleep)]
    if status_sleep:
        command += ["--status-sleep", str(status_sleep)]
    if image is not None:
        command += ["--image", str(image)]
    if image_home is not None:
        command += ["--image-home", str(image_home)]
    if announce:
        command += ["--announce"]
    return (*command, "--")


def bridge(
    *,
    claude: tuple[str, ...] = MISSING,
    codex: tuple[str, ...] = MISSING,
    environ: Mapping[str, str] | None = None,
    now: datetime = NOW,
    **settings: Any,
) -> Bridge:
    config = BridgeConfig(claude_command=claude, codex_command=codex, **settings)
    return Bridge(config, environ=environ, clock=lambda: now)


def calls(record: Path, kind: str = "run") -> list[dict[str, Any]]:
    """What the fake tool wrote down, one entry per time it was started."""
    if not record.exists():
        return []
    lines = record.read_text(encoding="utf-8").splitlines()
    return [entry for entry in map(json.loads, lines) if entry["kind"] == kind]


def after(argv: list[str], flag: str) -> str:
    """The value that follows a flag."""
    return argv[argv.index(flag) + 1]


def only(tool: str, command: tuple[str, ...], **settings: Any) -> Bridge:
    """A bridge that has one of the two tools."""
    if tool == "claude":
        return bridge(claude=command, **settings)
    return bridge(codex=command, **settings)


@dataclass(frozen=True)
class Exchange:
    """One call through a fake tool: what came back, and what the tool was given."""

    answer: dict[str, Any]
    # The sign-in check before the call, and the call itself, as the tool saw them.
    status: dict[str, Any]
    run: dict[str, Any]


def exchange(
    tool: str,
    folder: Path,
    make: Callable[[Bridge], dict[str, Any]],
    output: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> Exchange:
    """Make one call through a fake tool and keep both sides of it."""
    record = folder / "record.jsonl"
    studio = only(tool, fake(tool, output=output, record=record), environ=environ)
    answer = make(studio)
    (status,) = calls(record, "status")
    (run,) = calls(record)
    return Exchange(answer=answer, status=status, run=run)
