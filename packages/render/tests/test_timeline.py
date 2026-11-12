"""Timeline: the event list shared by picture and sound (design doc section 7.1)."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import pytest

from packages.render.tests import support
from packages.render.timeline import build_timeline


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    authored = support.sample_authored()
    authored["scenes"][1].setdefault("sound", []).append(
        {"cue_id": "stamp", "cue": {"after_narration_s": 0.1}, "gain_db": -3}
    )
    return support.resolve_sample(authored, "library/a_garden_dusk/v1.png")


def test_events_are_in_time_order(resolved: dict[str, Any]) -> None:
    events = build_timeline(resolved)

    assert events
    assert all(earlier.at_s <= later.at_s for earlier, later in pairwise(events))


def test_every_scene_starts_with_a_scene_event(resolved: dict[str, Any]) -> None:
    starts = [event for event in build_timeline(resolved) if event.kind == "scene"]

    assert [event.scene for event in starts] == list(range(len(resolved["scenes"])))
    assert [event.at_s for event in starts] == [scene["start_s"] for scene in resolved["scenes"]]
    assert starts[1].data["duration_s"] == resolved["scenes"][1]["duration_s"]


def test_narration_events_carry_the_audio_file_and_skip_silent_scenes(
    resolved: dict[str, Any],
) -> None:
    narrations = [event for event in build_timeline(resolved) if event.kind == "narration"]
    spoken = [scene for scene in resolved["scenes"] if scene["narration"]["audio_file"]]

    assert len(narrations) == len(spoken) < len(resolved["scenes"])
    assert narrations[0].at_s == spoken[0]["narration"]["start_s"]
    assert narrations[0].data["audio_file"] == spoken[0]["narration"]["audio_file"]
    assert narrations[0].data["duration_s"] == spoken[0]["narration"]["duration_s"]


def test_sound_events_carry_the_cue_and_its_gain(resolved: dict[str, Any]) -> None:
    sounds = [event for event in build_timeline(resolved) if event.kind == "sound"]
    stamp = next(event for event in sounds if event.data["cue_id"] == "stamp")
    in_spec = next(cue for cue in resolved["scenes"][1]["sound"] if cue["cue_id"] == "stamp")

    assert stamp.scene == 1
    assert stamp.at_s == in_spec["at_s"]
    assert stamp.data["gain_db"] == -3


def test_text_steps_and_overlays_are_events_too(resolved: dict[str, Any]) -> None:
    events = build_timeline(resolved)
    kinds = {event.kind for event in events}

    assert {"text", "step", "overlay"} <= kinds
    overlays = [event for event in events if event.kind == "overlay" and event.scene == 1]
    assert {event.data["type"] for event in overlays} == {
        overlay["type"] for overlay in resolved["scenes"][1]["overlays"]
    }


def test_a_smoke_transition_is_an_event_at_the_end_of_its_scene(resolved: dict[str, Any]) -> None:
    transitions = [event for event in build_timeline(resolved) if event.kind == "transition"]
    with_smoke = [
        index
        for index, scene in enumerate(resolved["scenes"])
        if scene.get("transition_out") == "smoke"
    ]

    assert [event.scene for event in transitions] == with_smoke
    first = resolved["scenes"][with_smoke[0]]
    assert transitions[0].at_s == pytest.approx(first["start_s"] + first["duration_s"])
    assert transitions[0].data["transition"] == "smoke"
