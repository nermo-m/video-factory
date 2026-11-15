"""How long a plan is estimated to take, before the voice exists (design doc section 5.2).

The real length is known only after the voice has spoken the narration, and the resolver
has the last word on it. Until then the script's word budget and the Plan tab's duration
bar use the same estimate, so they cannot disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

WORDS_PER_SECOND = 2.3
# The silence around each scene's narration (section 5.2: pad_before_s and pad_after_s).
PAUSE_PER_SCENE_S = 0.7
# The resolver accepts a video up to 2 seconds off its target (section 5.2).
TOLERANCE_S = 2.0
# The estimate is not exact: the real voice speaks a little faster or slower than 2.3
# words per second. A plan is called too long or too short only when it is more than
# this far outside the tolerance.
SLACK = 1.05
# The shortest and the longest video there can be, in seconds.
SHORTEST_S, LONGEST_S = 15, 180
# A silent shot that was given no length.
SILENT_SHOT_S = 3.0


def count_words(text: str) -> int:
    return len(text.split())


def scene_seconds(narration: str, speed: float = 1.0) -> float:
    """The estimated length of one scene: its words at speaking pace, plus its pause."""
    return count_words(narration) / (WORDS_PER_SECOND * speed) + PAUSE_PER_SCENE_S


def estimate(scene: Mapping[str, Any], speed: float = 1.0) -> float:
    """The estimated length of a scene of a spec. A silent scene declares its own length,
    and a scene may hold its last frame after the narration."""
    narration = str(scene.get("narration") or "")
    if scene.get("kind") == "shot":
        # A spoken line always wins over a length: a shot lasts as long as its line, or
        # longer when it was given more seconds.
        given = float(scene.get("duration_s") or 0)
        if not narration.strip():
            return given or SILENT_SHOT_S
        return max(scene_seconds(narration, speed), given)
    if not narration.strip() and "duration_s" in scene:
        return float(scene["duration_s"])
    return scene_seconds(narration, speed) + float(scene.get("hold_s") or 0)


def plan_seconds(spec: Mapping[str, Any]) -> float:
    """The estimated length of a whole plan."""
    speed = float(spec.get("voice", {}).get("speed", 1.0))
    return sum(estimate(scene, speed) for scene in spec.get("scenes", []))


def shown_length(spec: Mapping[str, Any]) -> int:
    """The length a plan of shots is shown with: what its scenes need, never less than
    the shortest and never more than the longest video there can be."""
    return int(min(LONGEST_S, max(SHORTEST_S, round(plan_seconds(spec)))))


def accepted_range(target_duration_s: float) -> tuple[float, float]:
    """The shortest and longest estimate that still counts as fitting the target."""
    return (
        (target_duration_s - TOLERANCE_S) / SLACK,
        (target_duration_s + TOLERANCE_S) * SLACK,
    )


def fits(estimated_s: float, target_duration_s: float) -> bool:
    low, high = accepted_range(target_duration_s)
    return low <= estimated_s <= high
