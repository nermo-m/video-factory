"""What a finished video file actually is, and whether that is what was asked for (RN-01).

`probe_video` asks ffprobe. `format_problems` compares the answer with the spec's format
and is pure, so it is tested without FFmpeg. The full quality checks (loudness, black or
frozen frames, text overflow) arrive with milestone M4. These are the format checks.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.render.frames import frame_at

FFPROBE = "ffprobe"
VIDEO_CODEC = "h264"
PIXEL_FORMAT = "yuv420p"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = 192_000
AUDIO_SAMPLE_RATE = 48000
# How far the measured audio bitrate may be from 192 kbps. Encoders aim, they do not hit.
_BITRATE_TOLERANCE = 0.1
_HEAD_BYTES = 1 << 20


class ProbeError(Exception):
    """The file could not be examined."""


@dataclass(frozen=True)
class VideoFacts:
    width: int
    height: int
    fps: float
    frames: int
    duration_s: float
    video_codec: str
    pixel_format: str
    audio_codec: str | None
    audio_bitrate: int
    audio_sample_rate: int
    audio_channels: int
    faststart: bool  # the index comes before the media data, so playback can start early


def _ratio(value: str) -> float:
    above, _, below = value.partition("/")
    return float(above) / float(below or 1) if float(below or 1) else 0.0


def probe_video(path: Path) -> VideoFacts:
    """Examine a video file with ffprobe. Every frame is counted, not estimated."""
    if not path.is_file():
        raise ProbeError(f"There is no file {path.name}.")
    command = [
        FFPROBE,
        "-v",
        "error",
        "-count_frames",
        "-show_entries",
        "stream=codec_type,codec_name,pix_fmt,width,height,avg_frame_rate,nb_read_frames,"
        "bit_rate,sample_rate,channels:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        # A fixed program name and an argument list, no shell.
        finished = subprocess.run(command, capture_output=True, check=True)  # noqa: S603
    except FileNotFoundError as error:
        raise ProbeError("ffprobe is not installed. It is part of the worker image.") from error
    except subprocess.CalledProcessError as error:
        said = error.stderr.decode("utf-8", errors="replace").strip()[-400:]
        raise ProbeError(f"ffprobe could not read {path.name}: {said}") from error

    answer: dict[str, Any] = json.loads(finished.stdout)
    streams = {stream["codec_type"]: stream for stream in answer.get("streams", [])}
    video = streams.get("video")
    if video is None:
        raise ProbeError(f"{path.name} has no video stream.")
    audio = streams.get("audio", {})
    with path.open("rb") as file:
        head = file.read(_HEAD_BYTES)
    index, media = head.find(b"moov"), head.find(b"mdat")
    return VideoFacts(
        width=int(video["width"]),
        height=int(video["height"]),
        fps=_ratio(video["avg_frame_rate"]),
        frames=int(video["nb_read_frames"]),
        duration_s=float(answer["format"]["duration"]),
        video_codec=video["codec_name"],
        pixel_format=video["pix_fmt"],
        audio_codec=audio.get("codec_name"),
        audio_bitrate=int(audio.get("bit_rate", 0)),
        audio_sample_rate=int(audio.get("sample_rate", 0)),
        audio_channels=int(audio.get("channels", 0)),
        faststart=index != -1 and (media == -1 or index < media),
    )


def format_problems(
    facts: VideoFacts, video_format: Mapping[str, Any], duration_s: float
) -> list[str]:
    """Everything about a file that is not what RN-01 and the spec's format ask for.

    `video_format` is the format of the resolved spec that was rendered (the preview
    format for a preview) and `duration_s` the length that spec resolved to.
    """
    problems: list[str] = []
    wanted_size = (video_format["width"], video_format["height"])
    if (facts.width, facts.height) != wanted_size:
        problems.append(
            f"The picture is {facts.width} by {facts.height}, not {wanted_size[0]} by "
            f"{wanted_size[1]}."
        )
    fps = video_format["fps"]
    if abs(facts.fps - fps) > 0.01:
        problems.append(f"The frame rate is {facts.fps:.2f}, not {fps}.")
    if facts.video_codec != VIDEO_CODEC:
        problems.append(f"The video codec is {facts.video_codec}, not {VIDEO_CODEC}.")
    if facts.pixel_format != PIXEL_FORMAT:
        problems.append(f"The pixel format is {facts.pixel_format}, not {PIXEL_FORMAT}.")
    if facts.audio_codec != AUDIO_CODEC:
        problems.append(f"The audio codec is {facts.audio_codec or 'missing'}, not {AUDIO_CODEC}.")
    elif abs(facts.audio_bitrate - AUDIO_BITRATE) > AUDIO_BITRATE * _BITRATE_TOLERANCE:
        problems.append(
            f"The audio bitrate is {facts.audio_bitrate // 1000} kbps, not "
            f"{AUDIO_BITRATE // 1000} kbps."
        )
    if facts.audio_codec == AUDIO_CODEC and (
        facts.audio_sample_rate != AUDIO_SAMPLE_RATE or facts.audio_channels != 2
    ):
        problems.append(
            f"The audio is {facts.audio_sample_rate} Hz with {facts.audio_channels} "
            f"channel(s), not {AUDIO_SAMPLE_RATE} Hz stereo."
        )
    if not facts.faststart:
        problems.append("The index is at the end of the file (no faststart).")
    expected_frames = frame_at(duration_s, fps)
    if facts.frames != expected_frames:
        problems.append(f"The video has {facts.frames} frames, not {expected_frames}.")
    if abs(facts.duration_s - duration_s) > 1.5 / fps:
        problems.append(
            f"The file is {facts.duration_s:.2f} seconds long, not {duration_s:.2f} seconds."
        )
    target = video_format.get("target_duration_s")
    if target is not None and abs(duration_s - target) > 2.0:
        problems.append(
            f"The video is {duration_s:.1f} seconds long, more than 2 seconds away from the "
            f"target of {target} seconds."
        )
    return problems
