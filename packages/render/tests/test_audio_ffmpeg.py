"""The audio mix, measured with FFmpeg's own loudness meter (design doc section 14.1).

The unit tests measure loudness with this project's code. Here the finished mix is written
to a file and FFmpeg's `ebur128` filter measures it, inside the pinned worker image, so
the limits of RN-09 are confirmed by a meter this project did not write.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from packages.render.audio import SAMPLE_RATE, AudioMix, mix_audio
from packages.render.loudness import integrated_lufs, true_peak_db
from packages.render.tests import support
from packages.render.theme import load_theme
from packages.render.wav import write_wav

pytestmark = pytest.mark.render

PICTURE = "library/a_garden_dusk/v1.png"


def ffmpeg_meter(path: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBFS) of a file, as FFmpeg measures them."""
    finished = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    summary = finished.stderr[finished.stderr.rindex("Summary:") :]
    loudness = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    assert loudness is not None, summary
    assert peak is not None, summary
    return float(loudness.group(1)), float(peak.group(1))


def ffprobe_duration(path: Path) -> float:
    finished = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return float(finished.stdout.strip())


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    authored = support.sample_authored()
    authored["scenes"][1]["sound"] = [{"cue_id": "stamp", "cue": {"scene_start_s": 1.0}}]
    authored["scenes"][0]["sound"] = [{"cue_id": "slam", "cue": {"word": 0}, "gain_db": 3}]
    return support.resolve_sample(authored, PICTURE)


@pytest.fixture(scope="module")
def mix(tmp_path_factory: pytest.TempPathFactory, resolved: dict[str, Any]) -> AudioMix:
    storage = tmp_path_factory.mktemp("storage")
    support.sample_voices(storage, resolved)
    return mix_audio(resolved, load_theme("night_scrolls"), storage_root=storage)


@pytest.fixture(scope="module")
def mix_file(tmp_path_factory: pytest.TempPathFactory, mix: AudioMix) -> Path:
    path = tmp_path_factory.mktemp("mix") / "mix.wav"
    write_wav(path, mix.samples, mix.sample_rate)
    return path


def test_rn09_ffmpeg_measures_the_mix_near_minus_14_lufs(mix_file: Path) -> None:
    loudness, _ = ffmpeg_meter(mix_file)

    assert loudness == pytest.approx(-14.0, abs=0.5)


def test_rn09_ffmpeg_measures_the_true_peak_under_minus_1_db(mix_file: Path) -> None:
    _, peak = ffmpeg_meter(mix_file)

    assert peak < -1.0


def test_this_projects_meter_agrees_with_ffmpeg(mix: AudioMix, mix_file: Path) -> None:
    loudness, peak = ffmpeg_meter(mix_file)

    assert mix.report.integrated_lufs == pytest.approx(loudness, abs=0.2)
    assert mix.report.true_peak_db == pytest.approx(peak, abs=0.3)


def test_the_meters_agree_on_the_ebu_reference_tone(tmp_path: Path) -> None:
    # EBU Tech 3341, case 1: a stereo 1 kHz sine at -23 dBFS reads -23.0 LUFS.
    steps = np.arange(20 * SAMPLE_RATE) / SAMPLE_RATE
    tone = (10 ** (-23 / 20) * np.sin(2 * np.pi * 1000 * steps)).astype(np.float32)
    stereo = np.stack([tone, tone], axis=1)
    write_wav(tmp_path / "tone.wav", stereo, SAMPLE_RATE)

    loudness, peak = ffmpeg_meter(tmp_path / "tone.wav")

    assert loudness == pytest.approx(-23.0, abs=0.1)
    assert integrated_lufs(stereo, SAMPLE_RATE) == pytest.approx(loudness, abs=0.1)
    assert true_peak_db(stereo, SAMPLE_RATE) == pytest.approx(peak, abs=0.1)


def test_the_audio_file_is_as_long_as_the_video(mix_file: Path, resolved: dict[str, Any]) -> None:
    last = resolved["scenes"][-1]

    assert ffprobe_duration(mix_file) == pytest.approx(
        last["start_s"] + last["duration_s"], abs=1 / 30
    )
