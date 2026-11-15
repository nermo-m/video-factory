"""What the owner switched on or off for one video (Director mode).

Nothing here is forced on a video. Research is off unless the owner asks for it, and
captions and music are on unless the owner turns them off. The choices are stored on the
episode as `options` and read through `options_of`, so an episode that was made before a
switch existed gets that switch's default.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EpisodeOptions:
    # Look facts up, with sources, before the plan is written.
    research: bool = False
    # Show the spoken words as captions.
    captions: bool = True
    # Play the studio's music bed under the video.
    music: bool = True

    def to_json(self) -> dict[str, bool]:
        return asdict(self)


NAMES = tuple(EpisodeOptions().to_json())


def options_of(stored: Mapping[str, Any] | None) -> EpisodeOptions:
    """The options of an episode from what is stored on it. A switch that is missing, or
    that is not a plain true or false, has its default."""
    given = stored or {}
    defaults = EpisodeOptions().to_json()
    return EpisodeOptions(
        **{
            name: given[name] if isinstance(given.get(name), bool) else default
            for name, default in defaults.items()
        }
    )


# --- who writes the plan -------------------------------------------------------------------

# The two tools that can write a plan in subscription mode, on the owner's own plans.
TOOLS = ("claude", "chatgpt")
# A model name as the host bridge takes it. It starts with a letter or a digit, so it can
# never be read as an option of the command line tool.
MODEL_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,79}"
WRITER_PATTERN = rf"^({'|'.join(TOOLS)})(:{MODEL_PATTERN})?$"
_WRITER = re.compile(WRITER_PATTERN)


@dataclass(frozen=True)
class Writer:
    """The tool and the model that write a video's plan. An empty tool leaves the choice
    to the studio, and no model leaves it to the settings and then to the tool itself."""

    tool: str = ""
    model: str | None = None

    @property
    def text(self) -> str:
        """The choice as it is stored and sent: `claude`, `chatgpt:gpt-5.5`, or nothing."""
        return f"{self.tool}:{self.model}" if self.model else self.tool


def parse_writer(written: object) -> Writer:
    """The writer a text names. Anything that is not a choice leaves it to the studio."""
    if not isinstance(written, str) or _WRITER.fullmatch(written) is None:
        return Writer()
    tool, _, model = written.partition(":")
    return Writer(tool=tool, model=model or None)


def writer_of(stored: Mapping[str, Any] | None) -> Writer:
    """Who writes the plan of an episode, from what is stored on it."""
    return parse_writer((stored or {}).get("writer"))


def stored_options(options: EpisodeOptions, writer: str) -> dict[str, Any]:
    """What is stored on an episode: its switches, and its writer when the owner chose one."""
    chosen = parse_writer(writer).text
    return {**options.to_json(), **({"writer": chosen} if chosen else {})}
