"""From a shot list to the plan the render engine draws (Director mode).

The shotlist skill writes what only a model can: the scenes, the picture prompts, the
motion, the characters. Everything the app already knows is written here, in ordinary
code: ids, the frame, the voice, the seed, the switches, one picture per scene. So the
model cannot get them wrong, and the owner's prompt passes through exactly one model call.

This module is pure. It reads a shot list and returns a plan of schema version 2.1.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from packages.core.lengths import LONGEST_S, SHORTEST_S, SILENT_SHOT_S, scene_seconds
from packages.skills import rules

SPEC_VERSION = "2.1"
THEME = "plain"
TEXT_STYLE = "plain"
WIDTH, HEIGHT, FPS = 1080, 1920, 30
# A stated length this much shorter than the lines need is worth telling the owner about.
# Less than that is within what the voice's own pace varies by.
WORTH_SAYING_S = 2.0


class TooLongError(Exception):
    """The owner's scenes need more time than a video can have. Nothing is cut: the owner
    decides what goes."""

    def __init__(self, needed_s: int) -> None:
        super().__init__(
            f"Your lines need about {needed_s} seconds and a video can be "
            f"{LONGEST_S} at most. Shorten the prompt or split it into two videos."
        )
        self.needed_s = needed_s


def _shot(scene: Mapping[str, Any], speed: float, changes: list[dict[str, Any]]) -> dict[str, Any]:
    narration = str(scene["narration"]).strip()
    visual: dict[str, Any] = {
        "asset_id": f"a_{scene['id']}",
        "clip": scene["clip"],
        "camera": scene["camera"],
        "motion": scene["motion_prompt"],
    }
    shot: dict[str, Any] = {"id": scene["id"], "kind": "shot", "narration": narration}
    if narration:
        shot["narration_from"] = scene["narration_from"]
    shot["visual"] = visual
    if scene["on_screen_text"]:
        shot["text"] = [
            {"content": item["content"], "style": TEXT_STYLE, "position": item["position"]}
            for item in scene["on_screen_text"]
        ]

    given = scene.get("duration_s")
    if not narration:
        shot["duration_s"] = given if given is not None else SILENT_SHOT_S
    elif given is not None:
        needed = scene_seconds(narration, speed)
        if given >= needed:
            shot["duration_s"] = given
        else:
            # A spoken line always wins over a length.
            changes.append(
                {
                    "scene": scene["id"],
                    "kind": "changed",
                    "what": "The scene lasts as long as its line.",
                    "why": f"The line takes about {round(needed)} seconds to speak and the "
                    f"scene was given {given:g}.",
                }
            )
    return shot


def build_spec(
    shotlist: Mapping[str, Any],
    *,
    episode_id: uuid.UUID,
    voice_id: str,
    voice_speed: float,
    captions: bool,
    music: bool,
    claims: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The plan for a shot list: one shot and one generated picture per scene.

    The length is what the scenes need. A length the owner stated that the lines do not
    fit into is listed as a change, never met by cutting. Raises TooLongError when the
    scenes need more than a video can have.
    """
    scenes: Sequence[Mapping[str, Any]] = shotlist["scenes"]
    changes: list[dict[str, Any]] = [dict(change) for change in shotlist["changes"]]
    shots = [_shot(scene, voice_speed, changes) for scene in scenes]

    needed = round(rules.needed_seconds(scenes, voice_speed))
    if needed > LONGEST_S:
        raise TooLongError(needed)
    stated = shotlist.get("target_duration_s")
    if stated is not None and needed - stated > WORTH_SAYING_S:
        changes.append(
            {
                "kind": "changed",
                "what": f"The video is about {needed} seconds long, not {stated:g}.",
                "why": "The lines take that long to speak, and a line is never cut.",
            }
        )

    return {
        "spec_version": SPEC_VERSION,
        "episode_id": str(episode_id),
        "format": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "target_duration_s": max(SHORTEST_S, needed),
        },
        "theme": THEME,
        "voice": {"voice_id": voice_id, "speed": voice_speed},
        # The same episode always gets the same seed, so a re-run draws the same frames.
        "seed": episode_id.int % 2**32,
        "style": shotlist["style"],
        "captions": captions,
        "music": music,
        "characters": [dict(character) for character in shotlist["characters"]],
        "changes": changes,
        "scenes": shots,
        "claims": [dict(claim) for claim in claims],
        "assets": [
            {
                "id": f"a_{scene['id']}",
                "kind": "image",
                "origin": "generated",
                "prompt": scene["image_prompt"],
                "characters": list(scene["characters"]),
                "text_in_picture": scene["text_in_picture"],
                "contains_third_party_ip": scene["third_party"],
                "rights_status": "needs_review",
            }
            for scene in scenes
        ],
    }
