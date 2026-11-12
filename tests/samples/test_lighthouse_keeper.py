"""The bundled demo episode, "The Lighthouse Keeper" (design doc section 13, FR-16).

It must work on a machine with no keys, no GPU, no accounts and no voice model: the spec,
its pictures and its narration are all in the repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from apps.worker import demo_render
from packages.adapters.tts.samples import SampleVoice
from packages.core import schemas
from packages.render.theme import check_capabilities, load_theme
from scripts import sample_pictures


@pytest.fixture(scope="module")
def authored() -> dict[str, Any]:
    return demo_render.load_sample()


def test_the_sample_is_a_valid_episode_spec(authored: dict[str, Any]) -> None:
    assert schemas.validate("episode_spec", authored) == []


def test_the_sample_asks_only_for_what_the_theme_can_draw(authored: dict[str, Any]) -> None:
    assert check_capabilities(authored, load_theme("night_scrolls").capabilities) == []


def test_the_sample_is_a_45_second_vertical_video(authored: dict[str, Any]) -> None:
    assert authored["format"] == {"width": 1080, "height": 1920, "fps": 30, "target_duration_s": 45}


def test_the_sample_has_no_statistic_so_it_needs_no_source(authored: dict[str, Any]) -> None:
    assert authored["claims"] == []
    assert all(scene["kind"] != "stat" for scene in authored["scenes"])


def test_rule2_every_picture_is_cleared_and_free_of_third_party_ip(
    authored: dict[str, Any],
) -> None:
    for asset in authored["assets"]:
        assert asset["rights_status"] == "cleared"
        assert asset["contains_third_party_ip"] is False
        assert asset["licence"] == "MIT"
        assert (demo_render.SAMPLE_DIR / "assets" / f"{asset['id']}.png").is_file()


def test_every_scene_shows_a_picture_the_sample_has(authored: dict[str, Any]) -> None:
    known = {asset["id"] for asset in authored["assets"]}
    shown = {scene["visual"]["asset_id"] for scene in authored["scenes"] if "visual" in scene}

    assert shown == known


@pytest.mark.parametrize("name", sorted(sample_pictures.PICTURES))
def test_rule2_committed_pictures_are_what_the_script_draws(name: str) -> None:
    with Image.open(demo_render.SAMPLE_DIR / "assets" / name) as committed:
        stored = np.asarray(committed.convert("RGB"), dtype=np.int16)
    fresh = np.asarray(sample_pictures.PICTURES[name]().convert("RGB"), dtype=np.int16)

    assert stored.shape == fresh.shape
    difference = np.abs(stored - fresh)
    assert int(difference.max()) <= 2, f"{name} was changed without the script"


def test_fr16_every_narration_has_a_bundled_recording(authored: dict[str, Any]) -> None:
    voice = SampleVoice(demo_render.VOICE_DIR)

    for scene in authored["scenes"]:
        narration = voice.synthesise(
            scene["narration"],
            voice_id=authored["voice"]["voice_id"],
            speed=authored["voice"]["speed"],
        )
        assert [word.text for word in narration.words] == scene["narration"].split()
        assert narration.sample_rate == 24000


def test_fr16_no_recording_is_left_over_from_an_older_script(authored: dict[str, Any]) -> None:
    recordings = list(demo_render.VOICE_DIR.glob("*.wav"))

    assert len(recordings) == len(authored["scenes"])


def test_with_the_bundled_voice_the_episode_is_45_seconds_long(
    authored: dict[str, Any], tmp_path: Path
) -> None:
    prepared = demo_render.prepare(authored, SampleVoice(demo_render.VOICE_DIR), tmp_path)
    last = prepared.resolved["scenes"][-1]
    length = last["start_s"] + last["duration_s"]

    assert schemas.validate("resolved_spec", prepared.resolved) == []
    assert length == pytest.approx(45.0, abs=2.0)
    # Every file the render engine will read is in the work folder.
    for scene in prepared.resolved["scenes"]:
        assert (prepared.storage / scene["narration"]["audio_file"]).is_file()
    for asset in prepared.resolved["assets"]:
        assert (prepared.storage / asset["file"]).is_file()


def test_nothing_important_happens_under_the_smoke(
    authored: dict[str, Any], tmp_path: Path
) -> None:
    # A tag or stamp that lands in the last moments of a scene is covered by the
    # transition before anyone can read it.
    prepared = demo_render.prepare(authored, SampleVoice(demo_render.VOICE_DIR), tmp_path)

    for scene in prepared.resolved["scenes"]:
        end = scene["start_s"] + scene["duration_s"]
        for item in scene["overlays"] + scene["text"] + scene.get("steps", []):
            assert item["at_s"] <= end - 0.9, f"{scene['id']}: {item} arrives too late to be read"
