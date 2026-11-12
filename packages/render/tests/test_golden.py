"""Golden frames for every primitive and scene kind (design doc section 14.1, FR-11).

These tests are marked `render` and run inside the pinned worker image, so fonts and
library versions never differ between machines:

    make render-test             compare with the approved frames
    make render-golden-update    approve the frames as they are drawn now

Each case names what it is there to catch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from packages.render.compositor import Compositor
from packages.render.primitives import ClipFrames
from packages.render.tests import support
from packages.render.theme import load_theme

pytestmark = pytest.mark.render

PICTURE = "library/a_garden_dusk/v1.png"


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("storage")
    support.sample_picture(folder)
    return folder


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    return support.resolve_sample(support.sample_authored(), PICTURE)


@pytest.fixture(scope="module")
def compositor(resolved: dict[str, Any], storage: Path) -> Compositor:
    return Compositor(resolved, load_theme("night_scrolls"), storage_root=storage)


def offset(resolved: dict[str, Any], scene: int, path: tuple[str, int]) -> float:
    """Seconds into a scene at which one of its events happens."""
    item = resolved["scenes"][scene][path[0]][path[1]]
    start: float = resolved["scenes"][scene]["start_s"]
    return float(item["at_s"]) - start


# name -> (scene index, seconds into the scene)
STILL_CASES: dict[str, tuple[int, float]] = {
    # Title scene, slam text settled, a caption with its current word highlighted.
    "title_settled": (0, 1.2),
    # The scroll while it is still unrolling: paper cut off, bottom roller part-way down.
    "scroll_unrolling": (1, 0.25),
    # A full scroll scene: title, label, sublabel, picture with pan and zoom, tag with
    # its pin, swaying lantern and risen moon.
    "scroll_story": (1, 3.2),
    # Smoke covering the outgoing scene, and clearing from the incoming one.
    "smoke_out": (1, 4.75),
    "smoke_in": (2, 0.12),
    # A statistic with its label and the source it came from.
    "stat": (2, 3.0),
    # Steps: two have arrived, the third has not.
    "steps_two_of_three": (3, 2.0),
    "steps_all": (3, 3.4),
    # A silent pause scene: slam text, no caption.
    "silent_pause": (4, 0.3),
    # The outro holding its closing line in the accent colour.
    "outro_hold": (5, 3.6),
}


@pytest.mark.parametrize("name", sorted(STILL_CASES))
def test_golden_frame(name: str, compositor: Compositor) -> None:
    scene, seconds = STILL_CASES[name]

    frame = compositor.render(scene, round(seconds * compositor.fps))

    support.assert_matches_golden(frame, name)


def test_golden_slam_impact(compositor: Compositor, resolved: dict[str, Any]) -> None:
    """Slam text one frame after it lands: oversized, with flash and shake."""
    seconds = offset(resolved, 0, ("text", 0)) + 0.034

    support.assert_matches_golden(
        compositor.render(0, round(seconds * compositor.fps)), "slam_impact"
    )


def test_golden_pin_in_flight(compositor: Compositor, resolved: dict[str, Any]) -> None:
    """The pin on its way to the tag, before the tag shows."""
    seconds = offset(resolved, 1, ("overlays", 0)) + 0.067

    support.assert_matches_golden(
        compositor.render(1, round(seconds * compositor.fps)), "pin_in_flight"
    )


def test_golden_stamp(compositor: Compositor, resolved: dict[str, Any]) -> None:
    """The red stamp pressed onto the scroll."""
    stamp = next(
        index
        for index, overlay in enumerate(resolved["scenes"][1]["overlays"])
        if overlay["type"] == "stamp"
    )
    seconds = offset(resolved, 1, ("overlays", stamp)) + 0.2

    support.assert_matches_golden(compositor.render(1, round(seconds * compositor.fps)), "stamp")


def test_golden_clip_frame(resolved: dict[str, Any], storage: Path) -> None:
    """A generated clip in the picture area: scaled, cropped and frozen on its last frame
    once the clip is over (RN-08)."""
    frames = [
        Image.new("RGB", (480, 832), (30 + step * 20, 90, 160 - step * 12)) for step in range(8)
    ]
    with_clip = dict(resolved)
    with_clip["scenes"] = [dict(scene) for scene in resolved["scenes"]]
    with_clip["scenes"][1]["visual"] = {"asset_id": "a_garden_dusk", "clip": True}
    compositor = Compositor(
        with_clip,
        load_theme("night_scrolls"),
        storage_root=storage,
        clips={"a_garden_dusk": ClipFrames(frames, fps=16)},
    )

    # 3.2 seconds in, the half-second clip is long over: its last frame is held.
    support.assert_matches_golden(compositor.render(1, round(3.2 * compositor.fps)), "clip_frozen")
