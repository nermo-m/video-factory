"""The instructions of the direct skill say what the design asks of it (section 6)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from packages.skills import rules
from packages.skills.planner import load_skill


@pytest.mark.parametrize(
    "phrase",
    [
        "You do not rewrite them",
        "Use only what `capabilities` lists",
        "retention_device",
        "every three seconds",
        "Words are counted from zero",
        "A picture stays visible",
        "Do not use `text`\n  in a `scroll` scene",
    ],
)
def test_the_instructions_ask_for_direct_rules(phrase: str) -> None:
    """Only the theme's capabilities and the script's own words."""
    assert phrase in load_skill("direct").instructions


# --- a picture stays visible -------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[4]


def sample_inputs_and_spec() -> tuple[dict[str, Any], dict[str, Any]]:
    folder = ROOT / "packages" / "skills" / "direct" / "examples"
    inputs = json.loads((folder / "lighthouse_keeper.input.json").read_text(encoding="utf-8"))
    spec = json.loads((folder / "lighthouse_keeper.output.json").read_text(encoding="utf-8"))
    return inputs, spec


def problems(spec: dict[str, Any], inputs: dict[str, Any]) -> list[str]:
    return rules.spec_follows_the_plan(inputs, spec, None)  # type: ignore[arg-type]


def test_the_sample_episode_keeps_every_picture_visible() -> None:
    inputs, spec = sample_inputs_and_spec()

    assert problems(spec, inputs) == []


def test_slammed_text_on_a_scroll_scene_is_sent_back() -> None:
    """Seen in the first live video: text slammed across the scroll hid the picture."""
    inputs, spec = sample_inputs_and_spec()
    covered = copy.deepcopy(spec)
    scroll = next(scene for scene in covered["scenes"] if scene["kind"] == "scroll")
    scroll["text"] = [{"content": "ONE SHORT STRETCH", "style": "slam", "cue": {"word": 2}}]

    found = problems(covered, inputs)

    assert len(found) == 1
    assert scroll["id"] in found[0]
    assert "slammed across its picture" in found[0]


def test_a_tag_and_a_stamp_on_one_scroll_scene_are_sent_back() -> None:
    inputs, spec = sample_inputs_and_spec()
    crowded = copy.deepcopy(spec)
    scroll = next(
        scene
        for scene in crowded["scenes"]
        if scene["kind"] == "scroll"
        and any(overlay["type"] == "tag" for overlay in scene.get("overlays", []))
    )
    scroll["overlays"].append(
        {"type": "stamp", "content": "DAILY", "color": "red", "cue": {"after_narration_s": 0.1}}
    )

    found = problems(crowded, inputs)

    assert len(found) == 1
    assert "2 tags and stamps" in found[0]


def test_text_on_a_title_or_outro_scene_is_fine() -> None:
    inputs, spec = sample_inputs_and_spec()

    with_text = [scene["kind"] for scene in spec["scenes"] if scene.get("text")]

    assert set(with_text) == {"title", "outro"}
    assert problems(spec, inputs) == []
