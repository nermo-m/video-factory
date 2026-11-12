"""Which scenes an edit of the spec makes stale (design doc section 4.2, last rule).

"Narration changed marks voice and render stale for that scene, visual or asset changed
marks render stale for that scene, timing changed marks render stale for that scene and
every later scene."
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from packages.core import schemas
from packages.core.stale import StaleScenes, affected_scenes

ALL = ("s01_hook", "s02_story", "s03_fact", "s04_steps", "s05_pause", "s06_outro")
SPOKEN = tuple(scene for scene in ALL if scene != "s05_pause")


@pytest.fixture
def old() -> dict[str, Any]:
    path = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid" / "all_scene_kinds.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def new(old: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(old)


def test_an_unchanged_spec_makes_nothing_stale(old: dict[str, Any], new: dict[str, Any]) -> None:
    assert affected_scenes(old, new) == StaleScenes()
    assert not affected_scenes(old, new)


def test_changed_narration_marks_voice_and_render_of_that_scene(
    old: dict[str, Any], new: dict[str, Any]
) -> None:
    new["scenes"][1]["narration"] = "She watered two rows before work."

    assert affected_scenes(old, new) == StaleScenes(voice=("s02_story",), render=("s02_story",))


def test_a_changed_visual_marks_render_of_that_scene_only(
    old: dict[str, Any], new: dict[str, Any]
) -> None:
    new["scenes"][1]["visual"]["clip"] = True

    assert affected_scenes(old, new) == StaleScenes(render=("s02_story",))


def test_a_changed_asset_marks_render_of_the_scenes_that_show_it(
    old: dict[str, Any], new: dict[str, Any]
) -> None:
    new["assets"][0]["tags"] = ["garden", "night"]

    assert affected_scenes(old, new) == StaleScenes(render=("s02_story",))


@pytest.mark.parametrize(
    "edit",
    [
        lambda scene: scene["text"][0].update(content="A NEW LINE"),
        lambda scene: scene["text"][0].update(cue={"word": 1}),
        lambda scene: scene.update(sound=[{"cue_id": "slam", "cue": {"word": 0}}]),
    ],
)
def test_what_a_scene_shows_or_plays_is_part_of_its_visual(
    old: dict[str, Any], new: dict[str, Any], edit: Any
) -> None:
    edit(new["scenes"][0])

    assert affected_scenes(old, new) == StaleScenes(render=("s01_hook",))


@pytest.mark.parametrize(
    "timing", [{"pad_after_s": 1.2}, {"pad_before_s": 0.6}, {"duration_s": 9.0}]
)
def test_changed_timing_marks_render_of_that_scene_and_every_later_one(
    old: dict[str, Any], new: dict[str, Any], timing: dict[str, float]
) -> None:
    new["scenes"][2].update(timing)

    assert affected_scenes(old, new) == StaleScenes(
        render=("s03_fact", "s04_steps", "s05_pause", "s06_outro")
    )


def test_a_changed_transition_marks_the_scene_it_leaves_and_the_scene_it_enters(
    old: dict[str, Any], new: dict[str, Any]
) -> None:
    new["scenes"][1]["transition_out"] = "cut"

    assert affected_scenes(old, new) == StaleScenes(render=("s02_story", "s03_fact"))


def test_a_note_that_is_never_drawn_makes_nothing_stale(
    old: dict[str, Any], new: dict[str, Any]
) -> None:
    new["scenes"][0]["retention_device"] = "A different question"

    assert affected_scenes(old, new) == StaleScenes()


def test_a_new_scene_needs_a_voice_and_moves_everything_after_it(
    old: dict[str, Any], new: dict[str, Any]
) -> None:
    extra = copy.deepcopy(old["scenes"][0])
    extra.update(id="s02b_more", narration="And then one more.")
    new["scenes"].insert(2, extra)

    assert affected_scenes(old, new) == StaleScenes(
        voice=("s02b_more",),
        render=("s02b_more", "s03_fact", "s04_steps", "s05_pause", "s06_outro"),
    )


def test_a_removed_scene_moves_everything_after_it(
    old: dict[str, Any], new: dict[str, Any]
) -> None:
    del new["scenes"][2]

    assert affected_scenes(old, new) == StaleScenes(render=("s04_steps", "s05_pause", "s06_outro"))


def test_another_voice_means_every_spoken_scene_again(
    old: dict[str, Any], new: dict[str, Any]
) -> None:
    new["voice"]["speed"] = 1.1

    assert affected_scenes(old, new) == StaleScenes(voice=SPOKEN, render=ALL)


@pytest.mark.parametrize("field", ["seed", "theme", "format"])
def test_the_seed_theme_or_format_mean_every_scene_is_drawn_again(
    old: dict[str, Any], new: dict[str, Any], field: str
) -> None:
    if field == "format":
        new["format"]["fps"] = 25
    else:
        new[field] = 12 if field == "seed" else "another_theme"

    assert affected_scenes(old, new) == StaleScenes(render=ALL)


def test_two_edits_add_up_in_scene_order(old: dict[str, Any], new: dict[str, Any]) -> None:
    new["scenes"][3]["narration"] = "Pick it. Shrink it. Repeat it daily."
    new["scenes"][0]["text"][0]["content"] = "ONE TINY THING"

    assert affected_scenes(old, new) == StaleScenes(
        voice=("s04_steps",), render=("s01_hook", "s04_steps")
    )


def test_stale_scenes_can_be_added_together_and_stored() -> None:
    first = StaleScenes(voice=("s02",), render=("s02",))
    second = StaleScenes(render=("s01", "s03"))

    merged = first.merged(second, order=["s01", "s02", "s03"])

    assert merged == StaleScenes(voice=("s02",), render=("s01", "s02", "s03"))
    assert StaleScenes.from_json(merged.to_json()) == merged
    assert StaleScenes.from_json({}) == StaleScenes()
