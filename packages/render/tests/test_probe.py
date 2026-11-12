"""Format checks on a finished video (RN-01), tested on facts without FFmpeg."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from packages.render.probe import ProbeError, VideoFacts, format_problems, probe_video

FORMAT = {"width": 1080, "height": 1920, "fps": 30, "target_duration_s": 45}
GOOD = VideoFacts(
    width=1080,
    height=1920,
    fps=30.0,
    frames=1341,
    duration_s=44.7,
    video_codec="h264",
    pixel_format="yuv420p",
    audio_codec="aac",
    audio_bitrate=192_080,
    audio_sample_rate=48000,
    audio_channels=2,
    faststart=True,
)


def test_rn01_a_correct_video_has_no_problems() -> None:
    assert format_problems(GOOD, FORMAT, 44.7) == []


@pytest.mark.parametrize(
    ("wrong", "said"),
    [
        (replace(GOOD, width=720, height=1280), "720 by 1280"),
        (replace(GOOD, fps=25.0), "frame rate is 25.00"),
        (replace(GOOD, video_codec="hevc"), "video codec is hevc"),
        (replace(GOOD, pixel_format="yuv444p"), "pixel format is yuv444p"),
        (replace(GOOD, audio_codec=None), "audio codec is missing"),
        (replace(GOOD, audio_codec="mp3"), "audio codec is mp3"),
        (replace(GOOD, audio_bitrate=128_000), "128 kbps"),
        (replace(GOOD, audio_sample_rate=44100), "44100 Hz"),
        (replace(GOOD, audio_channels=1), "1 channel"),
        (replace(GOOD, faststart=False), "faststart"),
        (replace(GOOD, frames=1300), "1300 frames, not 1341"),
        (replace(GOOD, duration_s=43.0), "43.00 seconds long"),
    ],
)
def test_rn01_each_wrong_property_is_named(wrong: VideoFacts, said: str) -> None:
    problems = format_problems(wrong, FORMAT, 44.7)

    assert any(said in problem for problem in problems), problems


def test_one_wrong_property_gives_one_problem() -> None:
    assert len(format_problems(replace(GOOD, pixel_format="yuv444p"), FORMAT, 44.7)) == 1


def test_a_video_far_from_its_target_length_is_a_problem() -> None:
    long = replace(GOOD, frames=1500, duration_s=50.0)

    problems = format_problems(long, FORMAT, 50.0)

    assert problems == [
        "The video is 50.0 seconds long, more than 2 seconds away from the target of 45 seconds."
    ]


def test_rn12_a_preview_is_checked_against_the_preview_format() -> None:
    preview = replace(GOOD, width=540, height=960, fps=15.0, frames=670)
    preview_format = {**FORMAT, "width": 540, "height": 960, "fps": 15}

    assert format_problems(preview, preview_format, 44.7) == []
    assert format_problems(preview, FORMAT, 44.7) != []


def test_a_file_that_is_not_there_cannot_be_probed(tmp_path: Path) -> None:
    with pytest.raises(ProbeError, match=r"video\.mp4"):
        probe_video(tmp_path / "video.mp4")
