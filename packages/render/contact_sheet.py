"""Contact sheet: one frame per scene at its busiest moment (design doc section 7.1).

The planner and the critic cannot watch a video. They look at these frames instead, and
the interface uses the sheet as the player's poster image. The busiest moment of a scene
is when everything it shows has arrived and settled, and the smoke of the transition has
not started to cover it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PIL import Image

from packages.render.compositor import SCROLL_KINDS, TRANSITION_S, UNROLL_S, Compositor
from packages.render.timeline import build_timeline

TILE = (270, 480)
# How long an element takes to land and stop moving after it appears.
SETTLE_S = 0.6
_VISUAL_EVENTS = ("text", "step", "overlay")
_MARGIN_S = 0.05


def busiest_moments(resolved: Mapping[str, Any]) -> list[float]:
    """For every scene, the seconds into the scene at which the most is on screen."""
    scenes = resolved["scenes"]
    appearances: dict[int, list[float]] = {}
    for event in build_timeline(resolved):
        if event.kind in _VISUAL_EVENTS:
            appearances.setdefault(event.scene, []).append(event.at_s)

    moments: list[float] = []
    for index, scene in enumerate(scenes):
        duration: float = scene["duration_s"]
        latest = duration - _MARGIN_S
        if scene.get("transition_out") == "smoke":
            latest = duration - TRANSITION_S - _MARGIN_S
        earliest = 0.0
        if index > 0 and scenes[index - 1].get("transition_out") == "smoke":
            earliest = TRANSITION_S
        if scene["kind"] in SCROLL_KINDS:
            earliest = max(earliest, UNROLL_S)

        arrivals = sorted(at_s - scene["start_s"] for at_s in appearances.get(index, []))
        moment = _settled_moment(arrivals, latest) if arrivals else duration / 2
        # Not covered by smoke comes first, then fully arrived, then inside the scene.
        moment = max(min(moment, latest), min(earliest, latest))
        moments.append(min(max(moment, 0.0), max(duration - _MARGIN_S, 0.0)))
    return moments


def _settled_moment(arrivals: list[float], latest: float) -> float:
    """The moment with the most elements on screen at which none is still landing.

    Normally that is shortly after the last element arrives. When the last one arrives too
    late to settle before the scene is over (or covered), the moment just before it is
    taken instead, and so on backwards. A scene too short for any of this is shown as late
    as possible.
    """
    limit = latest
    for arrival in reversed(arrivals):
        if arrival + SETTLE_S <= limit:
            return arrival + SETTLE_S if limit == latest else limit
        limit = arrival - _MARGIN_S
    return latest


def contact_sheet(compositor: Compositor, *, columns: int | None = None) -> Image.Image:
    """The scenes' busiest frames side by side, in rows of `columns` (default: one row)."""
    moments = busiest_moments(compositor.resolved)
    count = len(moments)
    columns = count if columns is None else max(1, columns)
    rows = -(-count // columns)
    sheet = Image.new("RGB", (columns * TILE[0], rows * TILE[1]), compositor.colors["night"])
    for index, moment in enumerate(moments):
        frame = min(round(moment * compositor.fps), compositor.frame_count(index) - 1)
        tile = compositor.render(index, frame).resize(TILE, Image.Resampling.LANCZOS)
        sheet.paste(tile, ((index % columns) * TILE[0], (index // columns) * TILE[1]))
    return sheet
