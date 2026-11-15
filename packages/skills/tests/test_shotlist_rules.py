"""The owner's prompt is the plan: what the code checks in a shot list (Director mode).

The model is told to keep the owner's lines, scenes and names. These rules do not take
its word for it.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from packages.render.theme import load_theme
from packages.skills import rules
from packages.skills.planner import SKILLS_DIR

EXAMPLES = SKILLS_DIR / "shotlist" / "examples"


def example(part: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (EXAMPLES / f"lighthouse_keeper.{part}.json").read_text(encoding="utf-8")
    )
    return loaded


def problems(output: dict[str, Any], inputs: dict[str, Any] | None = None) -> list[str]:
    return rules.shotlist_follows_the_owner(inputs or example("input"), output, None)


def scene(scene_id: str, narration: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": scene_id,
        "narration": narration,
        "narration_from": "owner",
        "on_screen_text": [],
        "image_prompt": "A steep green hill at dawn with a lighthouse at the top, seen from below.",
        "characters": [],
        "motion_prompt": "The grass moves in the wind.",
        "clip": False,
        "camera": "push_in",
        "third_party": False,
        "text_in_picture": False,
        **fields,
    }


def answer(scenes: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {
        "title": "The hill",
        "style": "Soft watercolour.",
        "characters": [],
        "scenes": scenes,
        "changes": [],
        **fields,
    }


def given(idea: str) -> dict[str, Any]:
    return {
        "idea": idea,
        "capabilities": load_theme("plain").capabilities,
        "voice_speed": 1.0,
        "claims": [],
    }


# --- which lines of the prompt are spoken lines --------------------------------------------


def test_marked_lines_finds_quotes_and_labels_in_order() -> None:
    idea = (
        "Scene 1, a hill at dawn. VO: The keeper climbed the same hill.\n"
        "Scene 2. Narration: “Nobody asked him to do it.”\n"
        'Scene 3. He says "the lamp was always burning" and smiles.\n'
        "Voiceover:   Small steps still count.  \n"
        "narrator: It still counts today.\n"
    )

    assert rules.marked_lines(idea) == [
        rules.Marked("The keeper climbed the same hill.", spoken=True),
        rules.Marked("Nobody asked him to do it.", spoken=True),
        rules.Marked("the lamp was always burning", spoken=False),
        rules.Marked("Small steps still count.", spoken=True),
        rules.Marked("It still counts today.", spoken=True),
    ]


def test_a_quoted_word_or_two_is_not_a_line() -> None:
    assert rules.marked_lines('The style is "film noir". Call it "The Hill".') == []


def test_a_prompt_without_marks_has_no_marked_lines() -> None:
    assert rules.marked_lines("A lighthouse keeper climbs a hill every morning.") == []


# --- the example ---------------------------------------------------------------------------


def test_the_example_keeps_everything_the_owner_wrote() -> None:
    assert problems(example("output")) == []


# --- the owner's lines stay the owner's ----------------------------------------------------


def test_curly_quotes_capitals_and_double_spaces_still_match() -> None:
    # The curly quotes are the point of this test: a prompt pasted from a text editor has them.
    inputs = given("Shot one.  VO: “Don’t stop,”  she said.   Every  evening she climbed.")  # noqa: RUF001
    made = answer([scene("s1", '"Don\'t stop," she said. every evening she climbed.')])

    assert problems(made, inputs) == []


def test_an_owner_line_that_is_not_in_the_prompt_is_reported() -> None:
    inputs = given("A keeper climbs a hill. VO: The keeper climbed the same hill.")
    made = answer([scene("s1", "The old keeper climbed that hill again.")])

    assert problems(made, inputs) == [
        "scene s1: the narration is marked as the owner's line, but it does not stand in "
        "the owner's prompt word for word. Use the owner's words, or mark it as written by "
        "the studio and list it in `changes`.",
        'the owner\'s line "The keeper climbed the same hill." is spoken in no scene. '
        "Every line the owner wrote is spoken word for word.",
    ]


def test_a_studio_line_without_a_change_entry_is_reported() -> None:
    inputs = given("A keeper climbs a hill every morning. Write the narration yourself.")
    made = answer([scene("s1", "Every morning he climbed.", narration_from="studio")])

    assert problems(made, inputs) == [
        "scene s1: the narration was written by the studio, so `changes` needs an entry for "
        "this scene that says so."
    ]


def test_a_studio_line_that_is_on_the_change_list_is_fine() -> None:
    inputs = given("A keeper climbs a hill every morning. Write the narration yourself.")
    made = answer(
        [scene("s1", "Every morning he climbed.", narration_from="studio")],
        changes=[
            {"scene": "s1", "kind": "added", "what": "The narration.", "why": "None was given."}
        ],
    )

    assert problems(made, inputs) == []


def test_a_dropped_marked_line_is_reported() -> None:
    inputs = given("VO: The keeper climbed the same hill.\nVO: Nobody asked him to do it.")
    made = answer([scene("s1", "The keeper climbed the same hill.")])

    assert problems(made, inputs) == [
        'the owner\'s line "Nobody asked him to do it." is spoken in no scene. '
        "Every line the owner wrote is spoken word for word."
    ]


def test_marked_lines_out_of_order_are_reported() -> None:
    inputs = given("VO: The keeper climbed the same hill.\nVO: Nobody asked him to do it.")
    made = answer(
        [
            scene("s1", "Nobody asked him to do it."),
            scene("s2", "The keeper climbed the same hill."),
        ]
    )

    assert problems(made, inputs) == [
        "the owner's lines are spoken in another order than the owner wrote them: "
        '"Nobody asked him to do it." comes before "The keeper climbed the same hill."'
    ]


def test_two_of_the_owners_lines_may_share_a_scene() -> None:
    inputs = given("VO: The keeper climbed the same hill.\nVO: Nobody asked him to do it.")
    made = answer([scene("s1", "The keeper climbed the same hill. Nobody asked him to do it.")])

    assert problems(made, inputs) == []


def test_a_quoted_passage_may_be_text_on_screen_or_in_the_picture() -> None:
    inputs = given(
        'A hill at dawn. On screen: "Small steps still count." '
        'A brass plate reads "keep the light burning".'
    )
    made = answer(
        [
            scene(
                "s1",
                "",
                duration_s=3,
                on_screen_text=[{"content": "Small steps still count.", "position": "middle"}],
                image_prompt="A hill at dawn. A brass plate that reads KEEP THE LIGHT BURNING.",
                text_in_picture=True,
            )
        ]
    )

    assert problems(made, inputs) == []


def test_a_quoted_passage_that_is_nowhere_in_the_plan_is_reported() -> None:
    inputs = given('A hill at dawn. On screen: "Small steps still count."')
    made = answer([scene("s1", "", duration_s=3)])

    assert problems(made, inputs) == [
        'the owner\'s words "Small steps still count." are nowhere in the plan. They must '
        "be spoken, shown as text on screen, or written into a picture, word for word."
    ]


def test_a_prompt_without_spoken_lines_has_nothing_to_report() -> None:
    inputs = given("Three pictures of a hill: at dawn, at noon, at night. Four seconds each.")
    made = answer([scene(name, "", duration_s=4) for name in ("s1_dawn", "s2_noon", "s3_night")])

    assert problems(made, inputs) == []


# --- what the plan points at ---------------------------------------------------------------


def test_a_character_a_scene_lists_must_be_described() -> None:
    made = copy.deepcopy(example("output"))
    made["characters"] = []

    found = problems(made)

    assert found
    assert all("the character 'keeper'" in problem for problem in found)


def test_two_scenes_cannot_share_an_id() -> None:
    made = copy.deepcopy(example("output"))
    made["scenes"][1]["id"] = made["scenes"][0]["id"]

    assert f"two scenes have the id '{made['scenes'][0]['id']}'." in problems(made)


def test_only_what_the_look_has_can_be_asked_for() -> None:
    made = copy.deepcopy(example("output"))
    made["scenes"][0]["camera"] = "whip_pan"
    made["scenes"][0]["on_screen_text"] = [{"content": "The hill", "position": "left"}]

    found = problems(made)

    first = made["scenes"][0]["id"]
    assert (
        f"scene {first}: the look has no camera move 'whip_pan'. It has: none, push_in, "
        "pull_out, pan_left, pan_right, tilt_up, tilt_down. List what was asked for in "
        "`changes` as not possible."
    ) in found
    assert any(f"scene {first}: the look has no text position 'left'" in item for item in found)


# --- how long the lines need ---------------------------------------------------------------


def test_needed_seconds_adds_the_lines_and_the_silent_shots() -> None:
    scenes = [
        scene("s1", "one two three four five six seven eight nine ten eleven twelve"),
        scene("s2", "", duration_s=4),
        scene("s3", ""),
    ]

    # 12 words at 2.3 a second and 0.7 s of pause, then 4 s, then the 3 s of a silent
    # shot that was given no length.
    assert round(rules.needed_seconds(scenes, 1.0), 2) == round(12 / 2.3 + 0.7 + 4 + 3, 2)


def test_a_scene_given_more_seconds_than_its_line_takes_keeps_them() -> None:
    scenes = [scene("s1", "one two three", duration_s=10)]

    assert rules.needed_seconds(scenes, 1.0) == 10
