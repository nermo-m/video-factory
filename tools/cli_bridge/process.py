"""Start a tool, give it its input, and wait for it with a time limit.

The tool gets its arguments as a list, never through a shell, so nothing in a request can
turn into a second command.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Finished:
    """What a tool left behind when it ended."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class ToolTimeoutError(Exception):
    """The tool did not finish in time and was stopped."""


def resolve(command: Sequence[str]) -> list[str] | None:
    """The command with its program as a full path, or None when it is not installed.

    On Windows only a real program counts. A `.cmd` or `.bat` wrapper would be run by the
    command interpreter, which reads the arguments a second time.
    """
    program = shutil.which(command[0])
    if program is None:
        return None
    if sys.platform == "win32" and Path(program).suffix.lower() not in {".exe", ".com"}:
        return None
    return [program, *command[1:]]


def detached() -> dict[str, Any]:
    """Popen arguments that give a process its own group and, on Windows, no window."""
    options: dict[str, Any]
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        options = {"creationflags": flags}
    else:
        options = {"start_new_session": True}
    return options


def run(
    command: Sequence[str],
    *,
    stdin: str,
    env: Mapping[str, str],
    cwd: Path,
    timeout_s: float,
) -> Finished:
    """Run one command to its end. Raises ToolTimeoutError after `timeout_s` seconds."""
    started = time.monotonic()
    process = subprocess.Popen(  # noqa: S603 - a list of arguments, no shell
        list(command),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=dict(env),
        shell=False,
        **detached(),
    )
    try:
        out, err = process.communicate(stdin.encode("utf-8"), timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _stop(process)
        raise ToolTimeoutError from None
    return Finished(
        exit_code=process.returncode,
        stdout=out.decode("utf-8", errors="replace"),
        stderr=err.decode("utf-8", errors="replace"),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _stop(process: subprocess.Popen[bytes]) -> None:
    """End a tool and everything it started."""
    if sys.platform == "win32":
        taskkill = Path(os.environ.get("SYSTEMROOT", "C:\\Windows")) / "System32" / "taskkill.exe"
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(  # noqa: S603 - a fixed system program with a process number
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=15,
                shell=False,
            )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired, OSError, ValueError):
        process.communicate(timeout=10)
