"""Encode, join and preview with the real FFmpeg (RN-01 to RN-05, RN-08, RN-12, FR-12).

Marked `render`: these run inside the pinned worker image (`make render-test`). The
preview size is used wherever the size does not matter, because it encodes eight times
faster. One test checks the full output size.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from packages.render.compositor import Compositor
from packages.render.encode import (
    EncodeError,
    RenderResult,
    encode_scene,
    for_preview,
    load_clip,
    render_video,
)
from packages.render.tests import support
from packages.render.theme import Theme, load_theme

pytestmark = pytest.mark.render

PICTURE = "library/a_garden_dusk/v1.png"


def probe(path: Path) -> dict[str, Any]:
    """What ffprobe says about a file, with its frames counted one by one."""
    finished = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,codec_name,pix_fmt,width,height,avg_frame_rate,nb_read_frames,"
            "duration,bit_rate,sample_rate,channels,color_space:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    loaded: dict[str, Any] = json.loads(finished.stdout)
    return loaded


def stream(path: Path, kind: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        item for item in probe(path)["streams"] if item["codec_type"] == kind
    )
    return found


def decoded_frame(path: Path, number: int, size: tuple[int, int]) -> np.ndarray:
    """Frame `number` of a video file, counted from zero, as RGB."""
    finished = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select=eq(n\\,{number})",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(finished.stdout, dtype=np.uint8).reshape(size[1], size[0], 3)


def difference(drawn: Image.Image, decoded: np.ndarray) -> float:
    return float(np.abs(np.asarray(drawn, dtype=np.int16) - decoded.astype(np.int16)).mean())


@pytest.fixture(scope="module")
def theme() -> Theme:
    return load_theme("night_scrolls")


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    authored = support.sample_authored()
    authored["scenes"][1]["sound"] = [{"cue_id": "paper_unroll", "cue": {"scene_start_s": 0.1}}]
    return support.resolve_sample(authored, PICTURE)


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory, resolved: dict[str, Any]) -> Path:
    folder = tmp_path_factory.mktemp("storage")
    support.sample_picture(folder)
    support.sample_voices(folder, resolved)
    return folder


@pytest.fixture(scope="module")
def folder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("render")


@pytest.fixture(scope="module")
def preview(resolved: dict[str, Any], theme: Theme, storage: Path, folder: Path) -> RenderResult:
    return render_video(resolved, theme, storage_root=storage, folder=folder, preview=True)


def video_s(resolved: dict[str, Any]) -> float:
    last = resolved["scenes"][-1]
    duration: float = last["start_s"] + last["duration_s"]
    return duration


# --- the finished file -------------------------------------------------------------------


def test_rn12_a_preview_is_540_by_960_at_15_fps(preview: RenderResult) -> None:
    video = stream(preview.video, "video")

    assert (video["width"], video["height"]) == (540, 960)
    assert video["avg_frame_rate"] == "15/1"
    assert preview.preview is True


def test_rn01_the_video_is_h264_yuv420p_with_aac_sound(preview: RenderResult) -> None:
    video, audio = stream(preview.video, "video"), stream(preview.video, "audio")

    assert video["codec_name"] == "h264"
    assert video["pix_fmt"] == "yuv420p"
    assert video["color_space"] == "bt709"
    assert audio["codec_name"] == "aac"
    assert audio["sample_rate"] == "48000"
    assert audio["channels"] == 2
    assert int(audio["bit_rate"]) == pytest.approx(192_000, rel=0.05)


def test_rn01_the_index_is_at_the_front_of_the_file(preview: RenderResult) -> None:
    content = preview.video.read_bytes()

    # "faststart": a player can begin before the whole file has arrived.
    assert 0 < content.find(b"moov") < content.find(b"mdat")


def test_the_video_has_every_frame_and_is_as_long_as_the_spec_says(
    preview: RenderResult, resolved: dict[str, Any]
) -> None:
    video = stream(preview.video, "video")
    expected_frames = sum(scene.frames for scene in preview.scenes)

    assert int(video["nb_read_frames"]) == expected_frames
    assert float(video["duration"]) == pytest.approx(video_s(resolved), abs=1 / 15)
    assert float(stream(preview.video, "audio")["duration"]) == pytest.approx(
        video_s(resolved), abs=0.05
    )
    assert preview.duration_s == pytest.approx(video_s(resolved))


def test_rn02_every_scene_has_its_own_file_with_the_same_settings(preview: RenderResult) -> None:
    settings = set()
    for scene in preview.scenes:
        video = stream(scene.path, "video")
        assert int(video["nb_read_frames"]) == scene.frames
        settings.add((video["codec_name"], video["pix_fmt"], video["width"], video["height"]))

    assert len({scene.path for scene in preview.scenes}) == len(preview.scenes)
    assert settings == {("h264", "yuv420p", 540, 960)}


def test_rn05_nothing_with_a_temporary_name_is_left_behind(
    preview: RenderResult, folder: Path
) -> None:
    names = [path.name for path in folder.rglob("*") if path.is_file()]

    assert not [name for name in names if "partial" in name or name.endswith(".txt")]
    assert preview.audio.is_file()


def test_the_contact_sheet_is_written_next_to_the_video(preview: RenderResult) -> None:
    with Image.open(preview.contact_sheet) as sheet:
        assert sheet.format == "JPEG"
        assert sheet.size == (len(preview.scenes) * 270, 480)


# --- frames survive the trip -------------------------------------------------------------


def test_a_frame_in_the_file_is_the_frame_that_was_drawn(
    preview: RenderResult, resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    drawing = Compositor(for_preview(resolved), theme, storage_root=storage)
    local = preview.scenes[1].frames // 2
    number = preview.scenes[0].frames + local

    decoded = decoded_frame(preview.video, number, (540, 960))

    # Compression and the change to video colours cost a few levels, not more.
    assert difference(drawing.render(1, local), decoded) < 4.0


def test_rn03_the_join_is_frame_exact(
    preview: RenderResult, resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    drawing = Compositor(for_preview(resolved), theme, storage_root=storage)
    first_of_third = preview.scenes[0].frames + preview.scenes[1].frames

    last_of_second = decoded_frame(preview.video, first_of_third - 1, (540, 960))
    first = decoded_frame(preview.video, first_of_third, (540, 960))

    assert difference(drawing.render(1, preview.scenes[1].frames - 1), last_of_second) < 4.0
    assert difference(drawing.render(2, 0), first) < 4.0


def test_rn01_a_full_size_scene_is_1080_by_1920_at_30_fps(
    resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    shortest = min(
        range(len(resolved["scenes"])), key=lambda index: resolved["scenes"][index]["duration_s"]
    )
    path = tmp_path / "scene.mp4"

    encode_scene(resolved, theme, shortest, path, storage)

    video = stream(path, "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert video["avg_frame_rate"] == "30/1"
    assert int(video["nb_read_frames"]) == round(resolved["scenes"][shortest]["duration_s"] * 30)


# --- re-rendering ------------------------------------------------------------------------


def test_fr12_changing_one_scene_re_encodes_only_that_scene(
    preview: RenderResult, resolved: dict[str, Any], theme: Theme, storage: Path, folder: Path
) -> None:
    before = {scene.path: scene.path.stat().st_mtime_ns for scene in preview.scenes}
    edited = copy.deepcopy(resolved)
    edited["scenes"][3]["steps"][0]["text"] = "Pick one small thing"

    again = render_video(edited, theme, storage_root=storage, folder=folder, preview=True)

    assert again.encoded == [resolved["scenes"][3]["id"]]
    for index, scene in enumerate(again.scenes):
        if index != 3:
            assert scene.path.stat().st_mtime_ns == before[scene.path]
    assert int(stream(again.video, "video")["nb_read_frames"]) == sum(
        scene.frames for scene in again.scenes
    )
    # The new video shows the edited scene.
    drawing = Compositor(for_preview(edited), theme, storage_root=storage)
    local = again.scenes[3].frames - 10
    number = sum(scene.frames for scene in again.scenes[:3]) + local
    assert difference(drawing.render(3, local), decoded_frame(again.video, number, (540, 960))) < 4


def test_rn04_rendering_again_without_a_change_encodes_nothing(
    resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    first = render_video(resolved, theme, storage_root=storage, folder=tmp_path, preview=True)

    again = render_video(resolved, theme, storage_root=storage, folder=tmp_path, preview=True)

    assert len(first.encoded) == len(resolved["scenes"])
    assert again.encoded == []


def test_scenes_encoded_side_by_side_give_the_same_video(
    preview: RenderResult, resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    parallel = render_video(
        resolved, theme, storage_root=storage, folder=tmp_path, preview=True, workers=3
    )

    assert [scene.frames for scene in parallel.scenes] == [scene.frames for scene in preview.scenes]
    assert stream(parallel.video, "video")["nb_read_frames"] == str(
        sum(scene.frames for scene in preview.scenes)
    )
    number = preview.scenes[0].frames + 20
    assert (
        float(
            np.abs(
                decoded_frame(parallel.video, number, (540, 960)).astype(np.int16)
                - decoded_frame(preview.video, number, (540, 960)).astype(np.int16)
            ).mean()
        )
        < 1.0
    )


# --- clips and failures ------------------------------------------------------------------


def test_rn08_a_clip_file_is_decoded_into_frames(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=480x832:rate=16:duration=0.5",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )

    frames = load_clip(clip)

    assert len(frames.frames) == 8
    assert frames.fps == pytest.approx(16.0)
    assert frames.frames[0].size == (480, 832)
    assert frames.at(10.0) is frames.frames[-1]


def test_rn08_a_scene_with_a_clip_plays_the_clip(
    resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    clip = storage / "library" / "a_garden_dusk" / "clip.mp4"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=480x832:rate=16:duration=1",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )
    with_clip = copy.deepcopy(for_preview(resolved))
    with_clip["scenes"][1]["visual"]["clip"] = True
    with_clip["assets"][0]["clip_file"] = "library/a_garden_dusk/clip.mp4"
    path = tmp_path / "scene.mp4"

    encode_scene(with_clip, theme, 1, path, storage)

    # The picture area in the middle of the scroll is red now, as the clip is.
    middle = decoded_frame(path, 40, (540, 960))[420, 250]
    assert middle[0] > 180
    assert middle[1] < 90


def test_a_missing_clip_file_is_named(tmp_path: Path) -> None:
    with pytest.raises(EncodeError, match=r"clip\.mp4"):
        load_clip(tmp_path / "clip.mp4")


def test_a_failed_encode_says_which_scene_and_what_ffmpeg_said(
    resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    nowhere = tmp_path / "no_such_folder" / "scene.mp4"

    with pytest.raises(EncodeError, match=resolved["scenes"][4]["id"]) as caught:
        encode_scene(for_preview(resolved), theme, 4, nowhere, storage)

    assert "No such file or directory" in str(caught.value)
