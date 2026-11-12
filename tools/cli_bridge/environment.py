"""The environment the bridge gives to the tools it starts (design doc section 3.4, FR-27).

`claude -p` uses an API key when one is present, even when the owner is signed in with a
plan, and both tools can be pointed at other endpoints through variables. So every variable
that belongs to a model provider or to one of the two tools is removed, and the few that
are known to be harmless and needed are let through by name. A variable that is removed by
mistake makes a tool fail where the owner can see it. One that is passed on by mistake
could bill a call per use without anyone noticing, which is the worse mistake.
"""

from __future__ import annotations

from collections.abc import Mapping

# Removed whatever follows the prefix: keys, tokens, endpoints, model and billing switches.
REMOVED_PREFIXES = ("ANTHROPIC_", "OPENAI_", "CLAUDE_", "CODEX_")
# Keys of any other provider.
REMOVED_PARTS = ("API_KEY",)
REMOVED_NAMES = frozenset(
    {
        # Set inside a Claude Code session. A bridge started from one must not pass it on.
        "CLAUDECODE",
        "AWS_BEARER_TOKEN_BEDROCK",
    }
)
# Let through although the prefix matches: they say where a tool keeps its own files or
# where a program it needs is installed. The bridge passes them on and never opens them.
KEPT_NAMES = frozenset({"CLAUDE_CONFIG_DIR", "CLAUDE_CODE_GIT_BASH_PATH", "CODEX_HOME"})


def is_removed(name: str) -> bool:
    """Whether a variable is kept away from the tools. Windows ignores case in names."""
    upper = name.upper()
    if upper in KEPT_NAMES:
        return False
    return (
        upper in REMOVED_NAMES
        or upper.startswith(REMOVED_PREFIXES)
        or any(part in upper for part in REMOVED_PARTS)
    )


def child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """A copy of an environment without the variables a tool must not see."""
    return {name: value for name, value in environ.items() if not is_removed(name)}
