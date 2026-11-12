"""The bridge itself: status of the two tools, and one model call at a time per tool.

Design doc section 3.4. Before every call the tool's sign-in is checked, in the same
cleaned environment the call will run in. A tool that is not signed in with a plan is not
started, so a call can never be billed per use (FR-27, FR-28).
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.cli_bridge import claude, codex
from tools.cli_bridge.config import BridgeConfig
from tools.cli_bridge.contract import ClaudeRequest, CodexRequest, ImageRequest
from tools.cli_bridge.environment import child_environment
from tools.cli_bridge.errors import (
    BUSY,
    NOT_INSTALLED,
    NOT_PLAN_SIGN_IN,
    NOT_SIGNED_IN,
    TIMEOUT,
    TOOL_FAILED,
    BridgeError,
)
from tools.cli_bridge.process import Finished, ToolTimeoutError, resolve, run

log = logging.getLogger(__name__)

SERVICE = "cli-bridge"
CONTRACT = "bridge/1"
_VERSION = re.compile(r"\d+\.\d+\.\d+")

SignIn = tuple[bool, str | None, str | None]


@dataclass
class _Tool:
    name: str
    title: str
    command: tuple[str, ...]
    variable: str
    login: str
    status_arguments: tuple[str, ...]
    sign_in: Callable[[Finished], SignIn]
    turn: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class ToolStatus:
    installed: bool = False
    version: str | None = None
    signed_in: bool = False
    billing: str | None = None
    plan: str | None = None
    message: str = ""
    # False when the tool did not answer the status check at all.
    answered: bool = True

    @property
    def ready(self) -> bool:
        return self.installed and self.signed_in and self.billing == "plan"


def local_now() -> datetime:
    """The time on this PC with its time zone, the clock the tools print reset times in."""
    return datetime.now().astimezone()


class Bridge:
    def __init__(
        self,
        config: BridgeConfig,
        *,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = local_now,
    ) -> None:
        self._config = config
        self._environ = environ if environ is not None else os.environ
        self._clock = clock
        self._claude = _Tool(
            name=claude.NAME,
            title="Claude Code",
            command=config.claude_command,
            variable="CLAUDE_BIN",
            login="claude auth login",
            status_arguments=claude.STATUS_ARGUMENTS,
            sign_in=claude.sign_in,
        )
        self._codex = _Tool(
            name=codex.NAME,
            title="Codex",
            command=config.codex_command,
            variable="CODEX_BIN",
            login="codex login",
            status_arguments=codex.STATUS_ARGUMENTS,
            sign_in=codex.sign_in,
        )

    @property
    def config(self) -> BridgeConfig:
        return self._config

    def health(self) -> dict[str, Any]:
        """Whether each tool is installed and signed in with a plan. Starts no model call."""
        tools = {}
        for tool in (self._claude, self._codex):
            status = self._status(tool, with_version=True)
            tools[tool.name] = {
                "installed": status.installed,
                "version": status.version,
                "signed_in": status.signed_in,
                "billing": status.billing,
                "plan": status.plan,
                "ready": status.ready,
                "busy": tool.turn.locked(),
                "message": status.message,
            }
        return {"service": SERVICE, "contract": CONTRACT, "pid": os.getpid(), "tools": tools}

    def claude(self, request: ClaudeRequest) -> dict[str, Any]:
        def build(work: Path, inputs: Path) -> tuple[list[str], str]:
            return claude.arguments(request, inputs=inputs), request.prompt

        def read(finished: Finished) -> dict[str, Any]:
            return claude.read(finished, request, now=self._clock())

        return self._call(self._claude, request.timeout_s, build, read)

    def codex(self, request: CodexRequest) -> dict[str, Any]:
        def build(work: Path, inputs: Path) -> tuple[list[str], str]:
            return codex.arguments(request, work=work, inputs=inputs), codex.prompt(request)

        def read(finished: Finished) -> dict[str, Any]:
            return codex.read(finished, request, now=self._clock())

        return self._call(self._codex, request.timeout_s, build, read)

    def codex_image(self, request: ImageRequest) -> dict[str, Any]:
        """One picture from Codex's image tool, on the owner's ChatGPT plan (FR-30)."""
        home = codex.images_home(child_environment(self._environ))

        def build(work: Path, inputs: Path) -> tuple[list[str], str]:
            return codex.image_arguments(request, work=work), codex.image_prompt(request)

        def read(finished: Finished) -> dict[str, Any]:
            return codex.read_image(finished, request, now=self._clock(), home=home)

        return self._call(self._codex, request.timeout_s, build, read)

    def _call(
        self,
        tool: _Tool,
        timeout_s: float | None,
        build: Callable[[Path, Path], tuple[list[str], str]],
        read: Callable[[Finished], dict[str, Any]],
    ) -> dict[str, Any]:
        """One model call, logged with its numbers and never with its text."""
        entry: dict[str, Any] = {"tool": tool.name, "outcome": "ok"}
        try:
            answer = self._run(tool, timeout_s, build, read)
            entry.update(
                duration_ms=answer["duration_ms"],
                input_tokens=answer["usage"]["input_tokens"],
                output_tokens=answer["usage"]["output_tokens"],
                turns=answer["turns"],
            )
            return answer
        except BridgeError as error:
            entry["outcome"] = error.code
            raise
        finally:
            log.info("bridge call", extra=entry)

    def _run(
        self,
        tool: _Tool,
        timeout_s: float | None,
        build: Callable[[Path, Path], tuple[list[str], str]],
        read: Callable[[Finished], dict[str, Any]],
    ) -> dict[str, Any]:
        if not tool.turn.acquire(timeout=self._config.queue_seconds):
            raise BridgeError(
                BUSY,
                f"{tool.title} is busy with another call. Try again later.",
                status=503,
                tool=tool.name,
            )
        try:
            command = self._ready(tool)
            limit = min(timeout_s or self._config.timeout_seconds, self._config.max_timeout_seconds)
            # The tool works in an empty folder, so no project file or project setting is
            # in reach. What the bridge itself hands over lies in a second folder.
            with tempfile.TemporaryDirectory(
                prefix="vf-bridge-", ignore_cleanup_errors=True
            ) as folder:
                work, inputs = Path(folder, "work"), Path(folder, "input")
                work.mkdir()
                inputs.mkdir()
                built, stdin = build(work, inputs)
                try:
                    finished = run(
                        [*command, *built],
                        stdin=stdin,
                        env=child_environment(self._environ),
                        cwd=work,
                        timeout_s=limit,
                    )
                except ToolTimeoutError:
                    raise BridgeError(
                        TIMEOUT,
                        f"{tool.title} did not finish in {limit:g} seconds and was stopped.",
                        status=504,
                        tool=tool.name,
                    ) from None
            answer = read(finished)
            answer["duration_ms"] = finished.duration_ms
            answer["billing"] = "plan"
            return answer
        finally:
            tool.turn.release()

    def _ready(self, tool: _Tool) -> list[str]:
        """The tool's command, or the reason it must not be started."""
        status = self._status(tool, with_version=False)
        command = resolve(tool.command)
        if not status.installed or command is None:
            raise BridgeError(NOT_INSTALLED, status.message, status=503, tool=tool.name)
        if not status.answered:
            raise BridgeError(TOOL_FAILED, status.message, status=502, tool=tool.name)
        if not status.signed_in:
            raise BridgeError(NOT_SIGNED_IN, status.message, status=503, tool=tool.name)
        if not status.ready:
            raise BridgeError(NOT_PLAN_SIGN_IN, status.message, status=503, tool=tool.name)
        return command

    def _status(self, tool: _Tool, *, with_version: bool) -> ToolStatus:
        command = resolve(tool.command)
        if command is None:
            return ToolStatus(
                message=(
                    f"The {tool.name} program was not found. Install {tool.title}, or set "
                    f"{tool.variable} to the full path of the program (on Windows the .exe)."
                )
            )
        env = child_environment(self._environ)
        seconds = self._config.status_timeout_seconds
        version = None
        try:
            with tempfile.TemporaryDirectory(
                prefix="vf-bridge-", ignore_cleanup_errors=True
            ) as folder:
                if with_version:
                    printed = run(
                        [*command, "--version"],
                        stdin="",
                        env=env,
                        cwd=Path(folder),
                        timeout_s=seconds,
                    )
                    found = _VERSION.search(printed.stdout)
                    version = found.group(0) if found is not None else None
                report = run(
                    [*command, *tool.status_arguments],
                    stdin="",
                    env=env,
                    cwd=Path(folder),
                    timeout_s=seconds,
                )
        except ToolTimeoutError:
            return ToolStatus(
                installed=True,
                version=version,
                answered=False,
                message=f"{tool.title} did not answer the status check in {seconds:g} seconds.",
            )
        except OSError:
            return ToolStatus(
                message=f"The {tool.name} program could not be started. Check {tool.variable}."
            )
        signed_in, billing, plan = tool.sign_in(report)
        if not signed_in:
            message = f"{tool.title} is not signed in. Run `{tool.login}` in a terminal on this PC."
        elif billing != "plan":
            message = (
                f"{tool.title} is signed in with an API key or another paid account, not "
                f"with a plan. The bridge only runs plan sign-ins, so that no call is billed "
                f"per use. Run `{tool.login}` and choose your plan."
            )
        else:
            message = ""
        return ToolStatus(
            installed=True,
            version=version,
            signed_in=signed_in,
            billing=billing,
            plan=plan,
            message=message,
        )
