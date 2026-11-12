"""Timeline: the event list shared by picture and sound (design doc section 7.1).

The resolved spec stores what happens scene by scene. The timeline is the same content as
one flat list in time order, so the audio mix can place narration and sound cues, and the
contact sheet can find the moment of a scene where the most is happening.

This module is pure: it only rearranges the resolved spec.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# Scene boundaries first, so everything inside a scene comes after the scene itself.
_ORDER = ("scene", "narration", "text", "step", "overlay", "sound", "transition")


@dataclass(frozen=True)
class Event:
    """One thing that happens at an absolute time, in seconds from the start of the video."""

    at_s: float
    scene: int  # index of the scene it belongs to
    kind: str  # scene, narration, text, step, overlay, sound or transition
    data: Mapping[str, Any] = field(default_factory=dict)


def build_timeline(resolved: Mapping[str, Any]) -> list[Event]:
    """Every event of a resolved spec, in time order."""
    events: list[Event] = []
    for index, scene in enumerate(resolved["scenes"]):
        events.append(
            Event(
                scene["start_s"],
                index,
                "scene",
                {"id": scene["id"], "kind": scene["kind"], "duration_s": scene["duration_s"]},
            )
        )
        narration = scene["narration"]
        if narration["audio_file"]:
            events.append(
                Event(
                    narration["start_s"],
                    index,
                    "narration",
                    {
                        "audio_file": narration["audio_file"],
                        "duration_s": narration["duration_s"],
                        "words": narration["words"],
                    },
                )
            )
        events.extend(Event(item["at_s"], index, "text", item) for item in scene["text"])
        events.extend(Event(item["at_s"], index, "step", item) for item in scene.get("steps", []))
        events.extend(Event(item["at_s"], index, "overlay", item) for item in scene["overlays"])
        events.extend(Event(item["at_s"], index, "sound", item) for item in scene["sound"])
        transition = scene.get("transition_out")
        if transition and transition != "cut":
            events.append(
                Event(
                    scene["start_s"] + scene["duration_s"],
                    index,
                    "transition",
                    {"transition": transition},
                )
            )
    return sorted(events, key=lambda event: (event.at_s, event.scene, _ORDER.index(event.kind)))
