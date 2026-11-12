"""Contact sheet: one frame per scene at its busiest moment (design doc section 7.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from packages.render.compositor import TRANSITION_S, Compositor
from packages.render.contact_sheet import SETTLE_S, TILE, busiest_moments, contact_sheet
from packages.render.tests import support
from packages.render.theme import load_theme

PICTURE = "library/a_garden_dusk/v1.png"


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    return support.resolve_sample(support.sample_authored(), PICTURE)


@pytest.fixture(scope="module")
def compositor(resolved: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> Compositor:
    storage = tmp_path_factory.mktemp("storage")
    support.sample_picture(storage)
    return Compositor(resolved, load_theme("night_scrolls"), storage_root=storage)


def test_there_is_one_moment_per_scene_and_it_lies_inside_the_scene(
    resolved: dict[str, Any],
) -> None:
    moments = busiest_moments(resolved)

    assert len(moments) == len(resolved["scenes"])
    for moment, scene in zip(moments, resolved["scenes"], strict=True):
        assert 0 <= moment < scene["duration_s"]


def test_the_busiest_moment_is_after_everything_has_appeared(resolved: dict[str, Any]) -> None:
    moments = busiest_moments(resolved)
    checked = 0
    for moment, scene in zip(moments, resolved["scenes"], strict=True):
        appearances = [
            item["at_s"] - scene["start_s"]
            for item in scene["text"] + scene["overlays"] + scene.get("steps", [])
        ]
        # A scene whose last element arrives while the smoke is already rolling in cannot
        # show it uncovered. Those are checked by the next test instead.
        if appearances and max(appearances) + 0.3 < scene["duration_s"] - TRANSITION_S:
            assert moment > max(appearances)
            checked += 1

    assert checked >= 3


def test_the_busiest_moment_is_before_the_smoke_covers_the_scene(
    resolved: dict[str, Any],
) -> None:
    moments = busiest_moments(resolved)

    for moment, scene in zip(moments, resolved["scenes"], strict=True):
        if scene.get("transition_out") == "smoke":
            assert moment <= scene["duration_s"] - TRANSITION_S


def test_a_scene_where_nothing_appears_is_shown_at_its_middle() -> None:
    scene = {
        "id": "s01",
        "kind": "title",
        "start_s": 4.0,
        "duration_s": 2.0,
        "narration": {"text": "", "audio_file": None, "start_s": 4.0, "duration_s": 0, "words": []},
        "text": [],
        "overlays": [],
        "sound": [],
    }

    assert busiest_moments({"scenes": [scene]}) == [pytest.approx(1.0)]


def test_the_sheet_has_one_tile_per_scene_in_order(
    compositor: Compositor, resolved: dict[str, Any]
) -> None:
    sheet = contact_sheet(compositor, columns=4)

    # Six scenes in rows of four: two rows.
    assert sheet.size == (4 * TILE[0], 2 * TILE[1])
    assert sheet.mode == "RGB"
    moments = busiest_moments(resolved)
    for index in (0, 3, 5):
        frame = compositor.render(index, round(moments[index] * compositor.fps))
        expected = np.asarray(frame.resize(TILE, Image.Resampling.LANCZOS), dtype=np.int16)
        left, top = (index % 4) * TILE[0], (index // 4) * TILE[1]
        tile = np.asarray(sheet.crop((left, top, left + TILE[0], top + TILE[1])), dtype=np.int16)
        assert float(np.abs(tile - expected).mean()) < 1.0


def test_the_sheet_can_be_saved_as_a_jpeg(compositor: Compositor, tmp_path: Path) -> None:
    path = tmp_path / "sheet.jpg"

    contact_sheet(compositor).save(path, quality=85)

    with Image.open(path) as saved:
        assert saved.format == "JPEG"
        assert saved.width == len(compositor.resolved["scenes"]) * TILE[0]


def test_a_frame_is_not_taken_while_something_is_still_landing(resolved: dict[str, Any]) -> None:
    # In the story scene the stamp lands 0.5 seconds before the end, when the smoke is
    # about to start. There is no settled moment that shows it, so the sheet shows the
    # scene just before the stamp, not the flash of its impact.
    story = resolved["scenes"][1]
    stamp = next(item for item in story["overlays"] if item["type"] == "stamp")
    others = [item["at_s"] for item in story["overlays"] + story["text"] if item is not stamp]

    moment = story["start_s"] + busiest_moments(resolved)[1]

    assert moment < stamp["at_s"]
    assert moment >= max(others) + SETTLE_S
