"""The compositor: frame N of scene S from the resolved spec (section 7.1, FR-11)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from packages.render.compositor import Compositor, RenderError, TextBox
from packages.render.tests import support
from packages.render.theme import Theme, load_theme

SMOKE = (24, 26, 44)


@pytest.fixture(scope="module")
def theme() -> Theme:
    return load_theme("night_scrolls")


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("storage")
    support.sample_picture(folder)
    return folder


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    return support.resolve_sample(support.sample_authored(), "library/a_garden_dusk/v1.png")


@pytest.fixture(scope="module")
def compositor(resolved: dict[str, Any], theme: Theme, storage: Path) -> Compositor:
    return Compositor(resolved, theme, storage_root=storage)


def frame_at(compositor: Compositor, scene: int, seconds: float) -> int:
    return round(seconds * compositor.fps)


def test_rn01_frames_are_1080_by_1920_rgb(compositor: Compositor) -> None:
    frame = compositor.render(0, 0)

    assert frame.size == (1080, 1920)
    assert frame.mode == "RGB"


def test_rn12_a_smaller_format_gives_smaller_frames(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    preview = copy.deepcopy(resolved)
    preview["format"].update({"width": 540, "height": 960, "fps": 15})

    small = Compositor(preview, theme, storage_root=storage)

    assert small.render(0, 3).size == (540, 960)
    assert small.frame_count(0) == round(preview["scenes"][0]["duration_s"] * 15)


def test_a_scene_has_duration_times_fps_frames(
    compositor: Compositor, resolved: dict[str, Any]
) -> None:
    for index, scene in enumerate(resolved["scenes"]):
        assert compositor.frame_count(index) == round(scene["duration_s"] * 30)


def test_fr11_the_same_resolved_spec_renders_identical_frames_twice(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    first = Compositor(resolved, theme, storage_root=storage)
    second = Compositor(copy.deepcopy(resolved), theme, storage_root=storage)

    for scene, seconds in [(0, 0.5), (1, 0.3), (1, 3.2), (2, 2.0), (3, 2.5), (5, 3.0)]:
        frame = frame_at(first, scene, seconds)
        assert first.render(scene, frame).tobytes() == second.render(scene, frame).tobytes()


def test_the_seed_changes_the_random_effects(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    other = copy.deepcopy(resolved)
    other["seed"] = resolved["seed"] + 1

    same = Compositor(resolved, theme, storage_root=storage).render(0, 20)
    different = Compositor(other, theme, storage_root=storage).render(0, 20)

    assert same.tobytes() != different.tobytes()


def long_text_spec() -> dict[str, Any]:
    """The sample episode with text that is far too long everywhere."""
    authored = support.sample_authored()
    long_words = "Extraordinarily unbelievably long words keep arriving relentlessly"
    hook, story, fact, steps, _pause, outro = authored["scenes"]
    hook["narration"] = long_words
    hook["text"] = [{"content": "X" * 80, "style": "slam", "cue": {"word": 0}}]
    story["title"] = "W" * 40
    story["label"] = "M" * 40
    story["sublabel"] = "m" * 60
    story["overlays"][0]["lines"] = ["W" * 24, "W" * 24, "W" * 24]
    story["overlays"][0]["cue"] = {"scene_start_s": 0.5}
    story["overlays"][2]["content"] = "W" * 24
    fact["stat"]["value"] = "W" * 16
    fact["stat"]["label"] = "W" * 60
    steps["steps"] = [{"text": "W" * 60}, {"text": "W" * 60}, {"text": "W" * 60}]
    outro["text"] = [
        {"content": "W" * 80, "style": "slam_accent", "cue": {"scene_start_s": 0}},
        {"content": "W" * 80, "style": "slam", "cue": {"scene_start_s": 0}},
    ]
    authored["format"]["target_duration_s"] = 24
    return authored


def test_rn07_no_text_or_key_art_in_the_bottom_15_or_right_12_percent(
    theme: Theme, storage: Path
) -> None:
    resolved = support.resolve_sample(long_text_spec(), "library/a_garden_dusk/v1.png")
    compositor = Compositor(resolved, theme, storage_root=storage)
    boxes: list[TextBox] = []
    for scene in range(len(resolved["scenes"])):
        for frame in range(0, compositor.frame_count(scene), 12):
            compositor.render(scene, frame, record=boxes)

    right_limit = round(1080 * 0.88)
    bottom_limit = round(1920 * 0.85)
    assert {box.kind for box in boxes} >= {
        "slam",
        "caption",
        "title",
        "label",
        "sublabel",
        "picture",
        "tag",
        "stamp",
        "stat_value",
        "stat_label",
        "stat_source",
        "step",
    }
    for box in boxes:
        left, top, right, bottom = box.box
        assert left >= 0, box
        assert top >= 0, box
        assert right <= right_limit, f"{box.kind} reaches into the right 12 percent: {box.box}"
        assert bottom <= bottom_limit, f"{box.kind} reaches into the bottom 15 percent: {box.box}"


def kinds_at(compositor: Compositor, scene: int, seconds: float) -> set[str]:
    boxes: list[TextBox] = []
    compositor.render(scene, frame_at(compositor, scene, seconds), record=boxes)
    return {box.kind for box in boxes}


def test_rn06_a_caption_shows_while_words_are_spoken_and_not_in_silence(
    compositor: Compositor, resolved: dict[str, Any]
) -> None:
    pause = next(i for i, scene in enumerate(resolved["scenes"]) if not scene["narration"]["text"])

    assert "caption" in kinds_at(compositor, 0, 1.0)
    assert "caption" not in kinds_at(compositor, 0, 0.1), "nothing is spoken before the pad ends"
    assert "caption" not in kinds_at(compositor, pause, 0.3)


def test_events_appear_at_their_time_and_not_before(
    compositor: Compositor, resolved: dict[str, Any]
) -> None:
    story = resolved["scenes"][1]
    tag_at = story["overlays"][0]["at_s"] - story["start_s"]
    stamp_at = next(o for o in story["overlays"] if o["type"] == "stamp")["at_s"] - story["start_s"]

    assert "tag" not in kinds_at(compositor, 1, tag_at - 0.1)
    assert "tag" in kinds_at(compositor, 1, tag_at + 0.5)
    assert "stamp" not in kinds_at(compositor, 1, stamp_at - 0.1)
    assert "stamp" in kinds_at(compositor, 1, stamp_at + 0.3)

    steps = resolved["scenes"][3]
    second_step = steps["steps"][1]["at_s"] - steps["start_s"]
    boxes: list[TextBox] = []
    compositor.render(3, frame_at(compositor, 3, second_step - 0.1), record=boxes)
    assert len([box for box in boxes if box.kind == "step"]) == 1


def paper_pixels(frame: Image.Image) -> int:
    pixels = np.asarray(frame, dtype=np.int16)
    close = np.abs(pixels - np.array([230, 211, 163])).max(axis=2) < 40
    return int(close.sum())


def test_a_scroll_unrolls_over_the_first_moments(compositor: Compositor) -> None:
    start = paper_pixels(compositor.render(1, 1))
    middle = paper_pixels(compositor.render(1, frame_at(compositor, 1, 0.25)))
    open_ = paper_pixels(compositor.render(1, frame_at(compositor, 1, 1.5)))

    assert start < middle < open_


def test_rn03_smoke_is_drawn_inside_both_scenes_so_the_join_is_seamless(
    compositor: Compositor, resolved: dict[str, Any]
) -> None:
    assert resolved["scenes"][1]["transition_out"] == "smoke"

    last_out = np.asarray(compositor.render(1, compositor.frame_count(1) - 1), dtype=np.int16)
    first_in = np.asarray(compositor.render(2, 0), dtype=np.int16)

    smoke_in = (np.abs(first_in - np.array(SMOKE)).max(axis=2) <= 2).mean()
    smoke_out = (np.abs(last_out - np.array(SMOKE)).max(axis=2) <= 2).mean()
    assert smoke_in == 1.0, "the incoming scene starts fully covered"
    assert smoke_out > 0.8, "the outgoing scene ends almost fully covered"
    # Half a second later the incoming scene is clear again.
    later = np.asarray(compositor.render(2, 15), dtype=np.int16)
    assert (np.abs(later - np.array(SMOKE)).max(axis=2) <= 2).mean() < 0.05


def test_fr05_a_missing_asset_file_stops_the_render_with_its_name(
    resolved: dict[str, Any], theme: Theme, tmp_path: Path
) -> None:
    empty = Compositor(resolved, theme, storage_root=tmp_path)
    nowhere = Compositor(resolved, theme)

    with pytest.raises(RenderError, match="'a_garden_dusk' is missing: library/a_garden_dusk"):
        empty.render(1, 30)
    with pytest.raises(RenderError, match="No storage folder was given"):
        nowhere.render(1, 30)
    # A scene without a picture needs no storage at all.
    assert nowhere.render(0, 10).size == (1080, 1920)
