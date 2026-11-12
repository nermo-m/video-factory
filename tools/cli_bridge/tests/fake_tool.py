"""A stand-in for the `claude` and `codex` command line tools, used by the bridge tests.

It answers the three things the bridge asks a tool: its version, whether it is signed in,
and one model call. For a model call it prints a recorded output file and writes down what
it was given, so a test can check the arguments, the input, the environment and the
working folder.

Usage: fake_tool.py --tool claude [options] -- <the arguments the bridge passes>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

VERSIONS = {"claude": "2.1.300 (Claude Code)", "codex": "codex-cli 0.144.1"}

# What `claude auth status --json` prints. The personal fields are here on purpose: the
# bridge must never pass them on.
CLAUDE_STATUS = {
    "plan": {
        "loggedIn": True,
        "authMethod": "claude.ai",
        "apiProvider": "firstParty",
        "email": "someone@example.com",
        "orgId": "00000000-0000-4000-8000-00000000abcd",
        "orgName": "Someone's Organisation",
        "subscriptionType": "max",
    },
    "api": {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"},
    "none": {"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"},
}
# What `codex login status` prints, on standard error.
CODEX_STATUS = {
    "plan": "Logged in using ChatGPT",
    "api": "Logged in using an API key - sk-proj-***ABCD",
    "none": "Not logged in",
}


def options(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", choices=("claude", "codex"), required=True)
    parser.add_argument("--sign-in", choices=("plan", "api", "none"), default="plan")
    parser.add_argument("--output", default=None, help="file printed for a model call")
    parser.add_argument("--stderr", default="")
    parser.add_argument("--exit", type=int, default=0, dest="exit_code")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--status-sleep", type=float, default=0.0)
    parser.add_argument("--record", default=None, help="file that gets one line per call")
    return parser.parse_args(arguments)


def record(chosen: argparse.Namespace, kind: str, given: list[str], stdin: str) -> None:
    if chosen.record is None:
        return
    entry = {
        "kind": kind,
        "argv": given,
        "stdin": stdin,
        "env": dict(os.environ),
        "cwd": str(Path.cwd()),
        "cwd_entries": sorted(entry.name for entry in Path.cwd().iterdir()),
        "files": {
            argument: Path(argument).read_text(encoding="utf-8")
            for argument in given
            if argument and Path(argument).is_file()
        },
    }
    with Path(chosen.record).open("a", encoding="utf-8") as lines:
        lines.write(json.dumps(entry) + "\n")


def main(argv: list[str]) -> int:
    split = argv.index("--")
    chosen = options(argv[:split])
    given = argv[split + 1 :]

    if given == ["--version"]:
        record(chosen, "version", given, "")
        sys.stdout.write(VERSIONS[chosen.tool] + "\n")
        return 0

    if given[:2] in (["auth", "status"], ["login", "status"]):
        record(chosen, "status", given, "")
        time.sleep(chosen.status_sleep)
        if chosen.tool == "claude":
            sys.stdout.write(json.dumps(CLAUDE_STATUS[chosen.sign_in], indent=2) + "\n")
        else:
            sys.stderr.write(CODEX_STATUS[chosen.sign_in] + "\n")
        return 0 if chosen.sign_in != "none" else 1

    stdin = sys.stdin.buffer.read().decode("utf-8")
    record(chosen, "run", given, stdin)
    time.sleep(chosen.sleep)
    if chosen.output is not None:
        sys.stdout.buffer.write(Path(chosen.output).read_bytes())
        sys.stdout.buffer.flush()
    sys.stderr.write(chosen.stderr)
    return int(chosen.exit_code)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
