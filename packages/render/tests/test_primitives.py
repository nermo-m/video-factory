"""Drawing primitives: the pure helpers the compositor is built from."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from packages.render import primitives as draw


def channel(image: Image.Image, index: int) -> int:
    """One colour channel of the top left pixel."""
    return int(np.asarray(image)[0, 0, index])


def solid(color: tuple[int, int, int, int], size: tuple[int, int] = (40, 30)) -> Image.Image:
    return Image.new("RGBA", size, color)


def test_easing_runs_from_zero_to_one_and_never_backwards() -> None:
    steps = [draw.ease_out(i / 20) for i in range(21)]

    assert (steps[0], steps[-1]) == (0, 1)
    assert steps == sorted(steps)
    assert draw.ease_out(-1) == 0
    assert draw.ease_out(2) == 1
    assert draw.ease_out_back(1) == 1
    assert max(draw.ease_out_back(i / 20) for i in range(21)) > 1, "it overshoots on the way"


def test_seeded_randomness_depends_only_on_the_seed_and_keys() -> None:
    first = draw.seeded(7, "s01", "tag", 0).uniform(0, 1, 4)
    again = draw.seeded(7, "s01", "tag", 0).uniform(0, 1, 4)
    other_key = draw.seeded(7, "s01", "tag", 1).uniform(0, 1, 4)
    other_seed = draw.seeded(8, "s01", "tag", 0).uniform(0, 1, 4)

    assert first.tolist() == again.tolist()
    assert first.tolist() != other_key.tolist()
    assert first.tolist() != other_seed.tolist()


def test_hex_colours_are_read_as_rgb() -> None:
    assert draw.hex_color("#FFC857") == (255, 200, 87)


@pytest.mark.parametrize(
    ("position", "expected_pixels"),
    [
        ((10, 10), 40 * 30),
        ((-20, -10), 20 * 20),
        ((90, 95), 10 * 5),
        ((200, 200), 0),
        ((-40, 0), 0),
    ],
)
def test_paste_crops_what_falls_outside_the_canvas(
    position: tuple[int, int], expected_pixels: int
) -> None:
    canvas = Image.new("RGBA", (100, 100), (0, 0, 0, 255))

    draw.paste(canvas, solid((255, 0, 0, 255)), *position)

    red = int((np.asarray(canvas)[:, :, 0] == 255).sum())
    assert red == expected_pixels


def test_opacity_scales_the_alpha_channel() -> None:
    half = draw.with_opacity(solid((10, 20, 30, 200)), 0.5)

    assert half.getpixel((0, 0)) == (10, 20, 30, 100)
    assert draw.with_opacity(solid((1, 2, 3, 200)), 1.5).getpixel((0, 0)) == (1, 2, 3, 200)
    assert channel(draw.with_opacity(solid((1, 2, 3, 200)), -1), 3) == 0


@pytest.mark.parametrize("source", [(1600, 400), (300, 1200), (680, 600), (64, 64)])
def test_rn08_cover_fills_the_picture_area_exactly(source: tuple[int, int]) -> None:
    image = Image.new("RGB", source, (50, 60, 70))

    assert draw.cover(image, 680, 600).size == (680, 600)
    assert draw.cover(image, 680, 600, zoom=1.12, pan=(0.2, 0.9)).size == (680, 600)


def test_rn08_cover_crops_instead_of_squashing() -> None:
    wide = Image.new("RGB", (400, 100), (0, 0, 0))
    wide.paste((255, 255, 255), (150, 0, 250, 100))

    filled = np.asarray(draw.cover(wide, 100, 100))

    # The middle of a wide image fills the square. Its dark sides are cropped away.
    assert filled.mean() > 250


def frames(count: int) -> list[Image.Image]:
    return [Image.new("RGB", (8, 8), (index, 0, 0)) for index in range(count)]


def test_rn08_a_short_clip_freezes_on_its_last_frame() -> None:
    clip = draw.ClipFrames(frames(10), fps=5)

    assert channel(clip.at(0), 0) == 0
    assert channel(clip.at(1.0), 0) == 5
    assert channel(clip.at(1.99), 0) == 9
    assert channel(clip.at(7.5), 0) == 9
    assert channel(clip.at(-1), 0) == 0


def test_rn08_a_looping_clip_starts_again() -> None:
    clip = draw.ClipFrames(frames(10), fps=5, mode="loop")

    assert channel(clip.at(2.0), 0) == 0
    assert channel(clip.at(2.6), 0) == 3


def test_shake_happens_only_right_after_an_impact_and_dies_down() -> None:
    assert draw.shake_offset(-0.1) == (0, 0)
    assert draw.shake_offset(0.3) == (0, 0)
    early = max(abs(value) for value in draw.shake_offset(0.02))
    late = max(abs(value) for value in draw.shake_offset(0.28))
    assert early > late
    assert early <= 14


def test_slam_text_starts_oversized_and_settles() -> None:
    assert draw.slam_scale(0) == 1.5
    assert 1 < draw.slam_scale(0.07) < 1.5
    assert draw.slam_scale(0.14) == 1.0
    assert draw.slam_scale(3) == 1.0


def test_rn03_smoke_covers_nothing_at_zero_and_everything_at_one() -> None:
    def frame() -> Image.Image:
        return Image.new("RGBA", (216, 384), (200, 180, 120, 255))

    clear, half, full = frame(), frame(), frame()
    draw.smoke(clear, 7, 0)
    draw.smoke(half, 7, 0.5)
    draw.smoke(full, 7, 1)

    assert np.asarray(clear).tolist() == np.asarray(frame()).tolist()
    assert len(full.getcolors() or []) == 1
    covered = (np.asarray(half)[:, :, 0] < 100).mean()
    assert 0.2 < covered < 0.95


def test_smoke_is_the_same_cloud_every_time() -> None:
    first = Image.new("RGBA", (216, 384), (200, 180, 120, 255))
    second = first.copy()

    draw.smoke(first, 7, 0.6)
    draw.smoke(second, 7, 0.6)

    assert first.tobytes() == second.tobytes()


def test_flash_fades_out() -> None:
    def brightness(since: float) -> int:
        frame = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
        draw.flash(frame, since)
        return int(channel(frame, 0))

    assert brightness(0) > brightness(0.06) > brightness(0.12) == 0
    assert brightness(-1) == 0


def test_an_unrolling_scroll_grows_from_the_top() -> None:
    paper = Image.new("RGBA", (100, 400), (230, 211, 163, 255))

    heights = [draw.unrolled(paper, progress).height for progress in (0, 0.25, 0.5, 1, 2)]

    assert heights[0] == 1
    assert heights == sorted(heights)
    assert heights[-2:] == [400, 400]
