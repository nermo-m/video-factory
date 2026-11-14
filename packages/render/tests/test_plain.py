"""The plain look: a shot is one picture on the whole frame (Director mode design).

No paper, no scroll, no decoration: the picture fills the frame, moves slowly, and the
owner's text and the captions sit on top of it in one neutral style.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from packages.core import schemas
from packages.render import primitives as draw
from packages.render.compositor import Compositor, TextBox
from packages.render.primitives import ClipFrames
from packages.render.resolver import AssetFile, NarrationTiming, WordTiming, resolve
from packages.render.theme import Theme, check_capabilities, load_theme

FRAME = (1080, 1920)
LINE = "Every evening she climbed the hill."
BLUE, RED, GREEN = (20, 40, 200), (220, 30, 30), (20, 180, 60)


@pytest.fixture(scope="module")
def theme() -> Theme:
    return load_theme("plain")


def marked(size: tuple[int, int]) -> Image.Image:
    """A blue picture with a red square exactly in its centre."""
    picture = Image.new("RGBA", size, (*BLUE, 255))
    cx, cy = size[0] // 2, size[1] // 2
    half = max(4, min(size) // 20)
    picture.paste((*RED, 255), (cx - half, cy - half, cx + half, cy + half))
    return picture


def red_box(image: Image.Image) -> tuple[int, int, int, int]:
    """Where the red square is in a frame: left, top, right, bottom."""
    red, green, _blue = image.convert("RGB").split()
    strong_red = Image.eval(red, lambda value: 255 if value > 180 else 0)
    little_green = Image.eval(green, lambda value: 255 if value < 90 else 0)
    box = Image.composite(strong_red, Image.new("L", image.size, 0), little_green).getbbox()
    assert box is not None, "the red square is not in the frame"
    return box


def brightest(image: Image.Image, at: tuple[int, int]) -> int:
    """The strongest colour channel of one pixel: 0 is black."""
    return max(image.convert("RGB").crop((at[0], at[1], at[0] + 1, at[1] + 1)).tobytes())


def centre(box: tuple[int, int, int, int]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


# --- the theme -----------------------------------------------------------------------


def test_the_plain_theme_loads(theme: Theme) -> None:
    assert theme.name == "plain"
    assert theme.fonts["body"].is_file()
    assert (theme.fonts["body"].parent / "Inter-OFL.txt").is_file()
    assert theme.backgrounds == []
    assert theme.sprites == {}
    assert theme.sounds == {}


def test_the_plain_look_draws_shots_and_nothing_else(theme: Theme) -> None:
    assert theme.capabilities == {
        "theme": "plain",
        "scene_kinds": ["shot"],
        "text_styles": ["plain"],
        "overlay_types": [],
        "stamp_colors": [],
        "sprites": {},
        "sound_cues": [],
        "transitions": ["cut", "fade"],
        "cameras": ["none", "push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down"],
        "text_positions": ["top", "middle", "bottom"],
    }


def test_the_shots_fixture_asks_only_for_what_the_plain_look_can_draw(theme: Theme) -> None:
    fixture = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid" / "shots.json"
    authored = json.loads(fixture.read_text(encoding="utf-8"))

    assert check_capabilities(authored, theme.capabilities) == []


def test_every_camera_move_the_look_lists_can_be_drawn(theme: Theme) -> None:
    picture = marked((540, 960))

    for camera in theme.capabilities["cameras"]:
        for progress in (0.0, 0.5, 1.0):
            assert draw.camera_frame(picture, (270, 480), camera, progress).size == (270, 480)


def test_a_camera_move_that_does_not_exist_is_an_error() -> None:
    with pytest.raises(ValueError, match="whip_pan"):
        draw.camera_frame(marked((540, 960)), (270, 480), "whip_pan", 0.5)


# --- the picture fills the frame and moves -------------------------------------------


@pytest.mark.parametrize("size", [(400, 200), (300, 300), (200, 500)])
def test_a_picture_of_any_shape_fills_the_frame_from_the_centre(size: tuple[int, int]) -> None:
    frame = draw.camera_frame(marked(size), (270, 480), "none", 0.0)

    assert frame.size == (270, 480)
    # No bars: every corner shows the picture.
    for corner in ((0, 0), (269, 0), (0, 479), (269, 479)):
        assert frame.convert("RGB").getpixel(corner) == BLUE
    x, y = centre(red_box(frame))
    assert abs(x - 135) <= 1.5
    assert abs(y - 240) <= 1.5


def test_none_does_not_move() -> None:
    picture = marked((540, 960))

    first = draw.camera_frame(picture, (270, 480), "none", 0.0)
    last = draw.camera_frame(picture, (270, 480), "none", 1.0)

    assert first.tobytes() == last.tobytes()


def test_push_in_ends_8_percent_closer() -> None:
    picture = marked((1080, 1920))

    start = red_box(draw.camera_frame(picture, FRAME, "push_in", 0.0))
    end = red_box(draw.camera_frame(picture, FRAME, "push_in", 1.0))

    assert (end[2] - end[0]) / (start[2] - start[0]) == pytest.approx(1.08, abs=0.02)
    assert centre(end) == pytest.approx(centre(start), abs=2)


def test_pull_out_is_push_in_backwards() -> None:
    picture = marked((540, 960))

    backwards = draw.camera_frame(picture, (270, 480), "pull_out", 0.0)

    assert backwards.tobytes() == draw.camera_frame(picture, (270, 480), "push_in", 1.0).tobytes()


def test_pan_left_turns_the_view_to_the_left() -> None:
    picture = marked((1080, 1920))

    start = centre(red_box(draw.camera_frame(picture, FRAME, "pan_left", 0.0)))
    end = centre(red_box(draw.camera_frame(picture, FRAME, "pan_left", 1.0)))

    # The view travels left across the picture, so what is in it drifts to the right.
    assert end[0] - start[0] == pytest.approx(1080 * 0.08, abs=3)
    assert end[1] == pytest.approx(start[1], abs=1)


def test_pan_right_and_the_tilts_travel_the_other_ways() -> None:
    picture = marked((1080, 1920))

    def travel(camera: str) -> tuple[float, float]:
        start = centre(red_box(draw.camera_frame(picture, FRAME, camera, 0.0)))
        end = centre(red_box(draw.camera_frame(picture, FRAME, camera, 1.0)))
        return (end[0] - start[0], end[1] - start[1])

    assert travel("pan_right")[0] == pytest.approx(-1080 * 0.08, abs=3)
    assert travel("tilt_up")[1] == pytest.approx(1920 * 0.08, abs=3)
    assert travel("tilt_down")[1] == pytest.approx(-1920 * 0.08, abs=3)


# --- whole frames ----------------------------------------------------------------------


def voice(scene_id: str, line: str, seconds_per_word: float = 0.5) -> NarrationTiming:
    words = line.split()
    return NarrationTiming(
        audio_file=f"voice/{scene_id}.wav",
        duration_s=len(words) * seconds_per_word,
        words=[
            WordTiming(word, i * seconds_per_word, (i + 1) * seconds_per_word)
            for i, word in enumerate(words)
        ],
    )


def plan(scenes: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {
        "spec_version": "2.1",
        "episode_id": "ep_plain",
        "format": {"width": 1080, "height": 1920, "fps": 30, "target_duration_s": 15},
        "theme": "plain",
        "voice": {"voice_id": "bm_george", "speed": 1.0},
        "seed": 3,
        "scenes": scenes,
        "claims": [],
        "assets": [
            {
                "id": "a_picture",
                "kind": "image",
                "origin": "uploaded",
                "licence": "made for this test",
                "contains_third_party_ip": False,
                "rights_status": "cleared",
            }
        ],
        **fields,
    }


def shot(scene_id: str, narration: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": scene_id,
        "kind": "shot",
        "narration": narration,
        "visual": {"asset_id": "a_picture", "camera": "none"},
        **fields,
    }


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("plain")
    # A landscape picture, as an owner might upload one.
    marked((1600, 900)).save(folder / "picture.png")
    return folder


def compositor(
    theme: Theme, storage: Path, scenes: list[dict[str, Any]], **fields: Any
) -> Compositor:
    authored = plan(scenes, **fields)
    voices = {
        scene["id"]: voice(scene["id"], scene["narration"])
        for scene in scenes
        if scene["narration"]
    }
    resolved = resolve(authored, voices, {"a_picture": AssetFile(file="picture.png")})
    return Compositor(resolved, theme, storage_root=storage)


def test_a_landscape_picture_fills_the_whole_frame_of_a_shot(theme: Theme, storage: Path) -> None:
    made = compositor(theme, storage, [shot("s1", "", duration_s=2)])

    frame = made.render(0, 0)

    assert frame.size == FRAME
    for corner in ((0, 0), (1079, 0), (0, 1919), (1079, 1919)):
        assert frame.getpixel(corner) == BLUE
    assert centre(red_box(frame)) == pytest.approx((540, 960), abs=2)


def test_a_shot_has_no_decoration_of_its_own(theme: Theme, storage: Path) -> None:
    made = compositor(theme, storage, [shot("s1", "", duration_s=2)])
    boxes: list[TextBox] = []

    frame = made.render(0, 30, record=boxes)

    assert boxes == []
    # Away from the red square the frame is the picture and nothing else.
    assert {frame.getpixel((x, y)) for x in (50, 540, 1030) for y in (60, 400, 1500, 1860)} == {
        BLUE
    }


def test_captions_are_drawn_over_the_picture(theme: Theme, storage: Path) -> None:
    made = compositor(theme, storage, [shot("s1", LINE)])
    boxes: list[TextBox] = []

    made.render(0, 30, record=boxes)

    assert [box.kind for box in boxes] == ["caption"]


def test_captions_off_draws_no_caption_box(theme: Theme, storage: Path) -> None:
    made = compositor(theme, storage, [shot("s1", LINE)], captions=False)
    boxes: list[TextBox] = []

    frame = made.render(0, 30, record=boxes)

    assert boxes == []
    assert {frame.getpixel((x, 1520)) for x in (120, 540, 900)} == {BLUE}


def test_on_screen_text_sits_where_it_was_put_and_clear_of_the_captions(
    theme: Theme, storage: Path
) -> None:
    text = [
        {"content": "Every evening", "style": "plain", "position": "top"},
        {"content": "the same hill", "style": "plain", "position": "middle"},
        {"content": "nobody asked her to", "style": "plain", "position": "bottom"},
    ]
    made = compositor(theme, storage, [shot("s1", LINE, text=text)])
    boxes: list[TextBox] = []

    made.render(0, 30, record=boxes)

    placed = {box.kind: box.box for box in boxes}
    assert set(placed) == {"text_top", "text_middle", "text_bottom", "caption"}
    assert placed["text_top"][3] <= placed["text_middle"][1]
    assert placed["text_middle"][3] <= placed["text_bottom"][1]
    assert placed["text_bottom"][3] <= placed["caption"][1]
    safe = theme.config["layout"]["safe_area"]
    for left, top, right, bottom in placed.values():
        assert left >= 1080 * safe["left"]
        assert top >= 1920 * safe["top"]
        assert right <= 1080 * (1 - safe["right"])
        assert bottom <= 1920 * (1 - safe["bottom"])


def test_text_appears_at_its_cue_and_not_before(theme: Theme, storage: Path) -> None:
    text = [{"content": "the hill", "style": "plain", "cue": {"word": 5}}]
    made = compositor(theme, storage, [shot("s1", LINE, text=text)], captions=False)
    before: list[TextBox] = []
    after: list[TextBox] = []

    made.render(0, 30, record=before)
    made.render(0, 100, record=after)

    assert before == []
    assert [box.kind for box in after] == ["text_bottom"]


def test_a_long_line_of_text_is_wrapped_onto_at_most_three_lines(
    theme: Theme, storage: Path
) -> None:
    long = "one small thing done every single day becomes a habit nobody can take away from you"
    text = [{"content": long[:80], "style": "plain", "position": "middle"}]
    made = compositor(theme, storage, [shot("s1", "", duration_s=2, text=text)])
    boxes: list[TextBox] = []

    made.render(0, 10, record=boxes)

    (box,) = boxes
    assert box.box[2] - box.box[0] <= theme.config["layout"]["text"]["middle"]["w"]
    assert box.box[3] - box.box[1] <= theme.config["layout"]["text"]["middle"]["h"]


def test_fade_goes_to_black_and_comes_back(theme: Theme, storage: Path) -> None:
    scenes = [
        shot("s1", "", duration_s=2, transition_out="fade"),
        shot("s2", "", duration_s=2),
    ]
    made = compositor(theme, storage, scenes)

    last_of_first = made.render(0, made.frame_count(0) - 1)
    first_of_second = made.render(1, 0)
    settled = made.render(1, 15)

    assert brightest(last_of_first, (50, 60)) < 40
    assert brightest(first_of_second, (50, 60)) < 40
    assert settled.getpixel((50, 60)) == BLUE


def test_a_cut_does_not_fade(theme: Theme, storage: Path) -> None:
    scenes = [shot("s1", "", duration_s=2), shot("s2", "", duration_s=2)]
    made = compositor(theme, storage, scenes)

    assert made.render(0, made.frame_count(0) - 1).getpixel((50, 60)) == BLUE
    assert made.render(1, 0).getpixel((50, 60)) == BLUE


def test_a_clip_plays_in_place_of_the_still_picture(theme: Theme, storage: Path) -> None:
    scene = shot("s1", "", duration_s=2, visual={"asset_id": "a_picture", "clip": True})
    authored = plan([scene])
    resolved = resolve(authored, {}, {"a_picture": AssetFile(file="picture.png")})
    clip = ClipFrames(frames=[Image.new("RGBA", (480, 832), (*GREEN, 255))], fps=16)
    made = Compositor(resolved, theme, storage_root=storage, clips={"a_picture": clip})

    assert made.render(0, 10).getpixel((540, 960)) == GREEN


def test_a_clip_scene_without_its_clip_shows_the_still_picture(theme: Theme, storage: Path) -> None:
    scene = shot("s1", "", duration_s=2, visual={"asset_id": "a_picture", "clip": True})
    made = compositor(theme, storage, [scene])

    assert made.render(0, 10).getpixel((50, 60)) == BLUE
