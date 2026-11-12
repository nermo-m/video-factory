"""Shared helpers for render tests: a sample episode, a stand-in picture and golden frames."""

from __future__ import annotations

import json
import os
import wave
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from packages.core import schemas
from packages.render.resolver import AssetFile, NarrationTiming, WordTiming, resolve

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
FAILED_DIR = Path(__file__).resolve().parent / "failed"
# Golden frames are stored small: enough to catch a wrong layout, colour or animation
# step, without filling the repository with full-size frames.
GOLDEN_SIZE = (270, 480)
MEAN_TOLERANCE = 1.2
CHANGED_SHARE_TOLERANCE = 0.004
SECONDS_PER_WORD = 0.5


def sample_picture(folder: Path) -> str:
    """Draw a simple original picture into the storage folder. Returns its storage path."""
    picture = Image.new("RGB", (900, 700))
    draw = ImageDraw.Draw(picture)
    for y in range(700):
        draw.line(((0, y), (900, y)), fill=(40 + y // 6, 60 + y // 9, 110 - y // 12))
    draw.ellipse((620, 80, 760, 220), fill=(250, 230, 170))
    draw.polygon(
        [(0, 700), (0, 480), (260, 330), (520, 520), (900, 400), (900, 700)], fill=(28, 46, 40)
    )
    path = folder / "library" / "a_garden_dusk" / "v1.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    picture.save(path)
    return "library/a_garden_dusk/v1.png"


def voice(scene: dict[str, Any]) -> NarrationTiming:
    """Voice timings with every word half a second long."""
    words = scene["narration"].split()
    return NarrationTiming(
        audio_file=f"voice/{scene['id']}.wav",
        duration_s=len(words) * SECONDS_PER_WORD,
        words=[
            WordTiming(word, i * SECONDS_PER_WORD, (i + 1) * SECONDS_PER_WORD)
            for i, word in enumerate(words)
        ],
    )


def sample_authored() -> dict[str, Any]:
    """The all-scene-kinds fixture, with a stamp, a rising moon and a sublabel added."""
    path = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid" / "all_scene_kinds.json"
    authored: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    authored["format"]["target_duration_s"] = 22
    story = authored["scenes"][1]
    story["sublabel"] = "nobody was watching"
    story["overlays"].append(
        {"type": "stamp", "content": "DAILY", "color": "red", "cue": {"after_narration_s": 0.1}}
    )
    story["overlays"].append(
        {"type": "sprite", "name": "moon", "action": "rise", "cue": {"scene_start_s": 0}}
    )
    return authored


def resolve_sample(authored: dict[str, Any], picture_path: str) -> dict[str, Any]:
    return resolve(
        authored,
        {scene["id"]: voice(scene) for scene in authored["scenes"] if scene["narration"]},
        {"a_garden_dusk": AssetFile(file=picture_path)},
    )


def assert_matches_golden(image: Image.Image, name: str) -> None:
    """Compare a rendered frame with its approved golden frame, within a tolerance.

    Set UPDATE_GOLDEN=1 to write the golden frames instead (make render-golden-update).
    """
    small = image.convert("RGB").resize(GOLDEN_SIZE, Image.Resampling.BOX)
    path = GOLDEN_DIR / f"{name}.png"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(exist_ok=True)
        small.save(path, optimize=True)
        return
    if not path.is_file():
        raise AssertionError(
            f"There is no golden frame '{name}'. Create it with: make render-golden-update"
        )

    with Image.open(path) as stored:
        expected = np.asarray(stored.convert("RGB"), dtype=np.int16)
    actual = np.asarray(small, dtype=np.int16)
    difference = np.abs(actual - expected)
    mean = float(difference.mean())
    changed = float((difference.max(axis=2) > 24).mean())
    if mean > MEAN_TOLERANCE or changed > CHANGED_SHARE_TOLERANCE:
        FAILED_DIR.mkdir(exist_ok=True)
        small.save(FAILED_DIR / f"{name}.png")
        raise AssertionError(
            f"The frame '{name}' differs from its golden frame: mean difference {mean:.2f} "
            f"(allowed {MEAN_TOLERANCE}), {changed:.2%} of pixels clearly changed (allowed "
            f"{CHANGED_SHARE_TOLERANCE:.2%}). The rendered frame was saved to "
            f"packages/render/tests/failed/{name}.png."
        )


def sample_voices(folder: Path, resolved: dict[str, Any]) -> None:
    """Write a stand-in narration file for every spoken scene: speech-like noise, 24 kHz mono.

    Not a voice, but it has what the mix cares about: the band of speech, syllables that
    rise and fall, and the length the resolved spec says the narration has.
    """
    rate = 24000
    for index, scene in enumerate(resolved["scenes"]):
        narration = scene["narration"]
        if not narration["audio_file"]:
            continue
        count = round(narration["duration_s"] * rate)
        steps = np.arange(count) / rate
        spectrum = np.fft.rfft(np.random.default_rng(100 + index).standard_normal(count))
        frequencies = np.fft.rfftfreq(count, 1 / rate)
        spectrum[(frequencies < 150) | (frequencies > 3500)] = 0
        noise = np.fft.irfft(spectrum, count)
        syllables = np.abs(np.sin(2 * np.pi * 2 * steps)) ** 0.7
        speech = noise * syllables
        speech = speech / np.abs(speech).max() * 0.5
        path = folder / narration["audio_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as sound:
            sound.setnchannels(1)
            sound.setsampwidth(2)
            sound.setframerate(rate)
            sound.writeframes(np.round(speech * 32767).astype("<i2").tobytes())
