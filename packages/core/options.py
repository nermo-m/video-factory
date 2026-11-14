"""What the owner switched on or off for one video (Director mode).

Nothing here is forced on a video. Research is off unless the owner asks for it, and
captions and music are on unless the owner turns them off. The choices are stored on the
episode as `options` and read through `options_of`, so an episode that was made before a
switch existed gets that switch's default.
"""

from __future__ import annotations

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
