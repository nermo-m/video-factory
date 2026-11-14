"""The instructions of the shotlist skill say what the owner asked for (Director mode).

The owner, on 2026-11-14: the videos "should follow full instructions I give and not
change them based on the preset", with "full on direction for every small detail".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packages.core import lengths
from packages.skills.planner import SKILLS_DIR, load_skill

ROOT = Path(__file__).resolve().parents[4]
EXAMPLES = SKILLS_DIR / "shotlist" / "examples"


def example(part: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (EXAMPLES / f"lighthouse_keeper.{part}.json").read_text(encoding="utf-8")
    )
    return loaded


@pytest.mark.parametrize(
    "phrase",
    [
        "The owner's prompt is the plan",
        "You do not improve it, restructure it, soften it or shorten it",
        "Leave none out and add none",
        "word for word",
        "Never replace a name with a description",
        "Every picture prompt stands on its own",
        "its background and its mood",
        "Describe what the owner describes",
        "not something safer",
        "Do not repeat a character's description in `image_prompt`",
        "`not_possible`",
        "nothing was changed quietly",
        "Never\nwrite a name that `capabilities` does not have",
    ],
)
def test_the_instructions_ask_to_follow_the_owner(phrase: str) -> None:
    assert phrase in load_skill("shotlist").instructions


def test_the_skill_is_version_1_0_and_thinks_hard() -> None:
    skill = load_skill("shotlist")

    assert (skill.version, skill.effort, skill.web_search) == ("1.0", "high", False)


def test_the_instructions_hold_no_trick_to_get_a_picture_past_a_filter() -> None:
    """A refused picture is replaced by the owner or made by a local model. The prompt
    is never dressed up to slip through."""
    text = load_skill("shotlist").instructions.lower()

    for word in ("bypass", "filter", "jailbreak", "avoid detection", "moderation", "euphemism"):
        assert word not in text, word


def test_the_recording_is_the_example_and_carries_the_skills_version() -> None:
    recording = json.loads(
        (ROOT / "samples" / "recordings" / "shotlist.json").read_text(encoding="utf-8")
    )

    assert recording["skill"] == "shotlist"
    assert recording["skill_version"] == load_skill("shotlist").version
    assert recording["output"] == example("output")


def test_the_example_speaks_every_line_of_its_prompt() -> None:
    idea: str = example("input")["idea"]
    spoken = [scene["narration"] for scene in example("output")["scenes"] if scene["narration"]]

    assert len(spoken) == 4
    for line in spoken:
        assert f"VO: {line}" in idea


def test_the_example_keeps_the_owners_scenes_in_order_and_adds_none() -> None:
    output = example("output")

    assert [scene["id"] for scene in output["scenes"]] == [
        "hill_dawn",
        "lamp_room",
        "storm_sea",
        "lighthouse_beam",
        "morning_after",
    ]
    assert [scene["clip"] for scene in output["scenes"]] == [False, False, True, False, False]
    assert output["scenes"][4]["on_screen_text"] == [
        {"content": "Small steps still count.", "position": "middle"}
    ]


def test_the_example_describes_its_character_once() -> None:
    output = example("output")
    (keeper,) = output["characters"]

    # The owner's own description of him, with a capital at the start.
    assert keeper["description"].lower() in example("input")["idea"].lower()
    for scene in output["scenes"]:
        assert "grey beard" not in scene["image_prompt"]
        assert "navy wool coat" not in scene["image_prompt"]


def test_every_picture_prompt_of_the_example_is_a_full_description() -> None:
    for scene in example("output")["scenes"]:
        assert lengths.count_words(scene["image_prompt"]) >= 40, scene["id"]


def test_the_example_lists_what_it_added_and_what_it_could_not_do() -> None:
    changes = example("output")["changes"]

    assert {change["kind"] for change in changes} == {"added", "not_possible"}
    (impossible,) = [change for change in changes if change["kind"] == "not_possible"]
    assert "piano" in impossible["what"]


def test_nothing_in_the_example_belongs_to_someone_else() -> None:
    assert not any(scene["third_party"] for scene in example("output")["scenes"])


def test_demo_mode_has_a_voice_and_a_picture_for_the_example() -> None:
    """Demo mode plays bundled recordings, found by the exact words, and bundled pictures,
    found by the picture's name. So the example speaks the sample episode's lines and
    names its scenes after the sample pictures."""
    sample = json.loads(
        (ROOT / "samples" / "lighthouse_keeper" / "episode_spec.json").read_text(encoding="utf-8")
    )
    recorded_lines = {scene["narration"] for scene in sample["scenes"]}
    bundled = {
        path.stem for path in (ROOT / "samples" / "lighthouse_keeper" / "assets").glob("*.png")
    }
    scenes = example("output")["scenes"]

    for scene in scenes:
        if scene["narration"]:
            assert scene["narration"] in recorded_lines, scene["id"]
    assert {f"a_{scene['id']}" for scene in scenes[:4]} == bundled
