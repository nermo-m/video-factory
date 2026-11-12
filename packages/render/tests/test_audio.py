"""Audio mix (RN-09): narration and sound cues on the timeline, music bed with ducking,
loudness normalisation.

The limits are measured here on the finished mix and its stems, not read from the mix's
own report, so a wrong report cannot hide a wrong mix.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from packages.render.audio import (
    OPEN_LIFT_DB,
    SAMPLE_RATE,
    AudioError,
    AudioMix,
    duck_gain_db,
    limiter_gain,
    mix_audio,
    music_bed,
)
from packages.render.loudness import integrated_lufs, true_peak_db
from packages.render.tests import support
from packages.render.theme import Theme, load_theme

PICTURE = "library/a_garden_dusk/v1.png"


def decibels(samples: np.ndarray) -> float:
    """Level of a stretch of audio (root mean square), in dB relative to full scale."""
    power = float((np.asarray(samples, dtype=np.float64) ** 2).mean())
    return 10 * np.log10(power) if power > 0 else float("-inf")


def stretch(samples: np.ndarray, start_s: float, end_s: float) -> np.ndarray:
    return samples[round(start_s * SAMPLE_RATE) : round(end_s * SAMPLE_RATE)]


def authored_with_cue() -> dict[str, Any]:
    authored = support.sample_authored()
    authored["scenes"][1]["sound"] = [{"cue_id": "stamp", "cue": {"scene_start_s": 1.0}}]
    return authored


@pytest.fixture(scope="module")
def theme() -> Theme:
    return load_theme("night_scrolls")


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    return support.resolve_sample(authored_with_cue(), PICTURE)


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory, resolved: dict[str, Any]) -> Path:
    folder = tmp_path_factory.mktemp("storage")
    support.sample_voices(folder, resolved)
    return folder


@pytest.fixture(scope="module")
def mix(resolved: dict[str, Any], theme: Theme, storage: Path) -> AudioMix:
    return mix_audio(resolved, theme, storage_root=storage)


def spoken_spans(resolved: dict[str, Any]) -> list[tuple[float, float]]:
    return [
        (scene["narration"]["words"][0]["start_s"], scene["narration"]["words"][-1]["end_s"])
        for scene in resolved["scenes"]
        if scene["narration"]["words"]
    ]


# --- shape -----------------------------------------------------------------------------


def test_the_mix_is_48_khz_stereo_and_exactly_as_long_as_the_video(
    mix: AudioMix, resolved: dict[str, Any]
) -> None:
    last = resolved["scenes"][-1]
    video_s = last["start_s"] + last["duration_s"]

    assert mix.sample_rate == 48000
    assert mix.samples.shape == (round(video_s * 48000), 2)
    assert mix.samples.dtype == np.float32
    assert mix.report.duration_s == pytest.approx(video_s)


def test_the_stems_add_up_to_the_mix(mix: AudioMix) -> None:
    together = mix.voice + mix.effects + mix.music

    assert float(np.abs(together - mix.samples).max()) < 1e-4


# --- placement -------------------------------------------------------------------------


def test_narration_starts_where_the_resolved_spec_says(
    mix: AudioMix, resolved: dict[str, Any]
) -> None:
    second = resolved["scenes"][1]
    start = second["narration"]["start_s"]

    # The scene opens with its pad of silence, then the voice comes in.
    assert decibels(stretch(mix.voice, second["start_s"] + 0.02, start - 0.02)) == float("-inf")
    assert decibels(stretch(mix.voice, start, start + 0.5)) > -40


def test_a_scene_without_narration_has_no_voice(mix: AudioMix, resolved: dict[str, Any]) -> None:
    silent = next(scene for scene in resolved["scenes"] if not scene["narration"]["audio_file"])

    assert decibels(
        stretch(mix.voice, silent["start_s"] + 0.05, silent["start_s"] + silent["duration_s"])
    ) == float("-inf")


def test_a_sound_cue_plays_at_its_time(mix: AudioMix, resolved: dict[str, Any]) -> None:
    cue = resolved["scenes"][1]["sound"][0]

    assert decibels(stretch(mix.effects, cue["at_s"] - 0.5, cue["at_s"] - 0.01)) == float("-inf")
    assert decibels(stretch(mix.effects, cue["at_s"], cue["at_s"] + 0.2)) > -50


def test_gain_db_moves_a_cue_by_that_many_decibels(theme: Theme, storage: Path) -> None:
    def cue_over_voice(gain_db: float) -> float:
        authored = authored_with_cue()
        authored["scenes"][1]["sound"][0]["gain_db"] = gain_db
        resolved = support.resolve_sample(authored, PICTURE)
        mixed = mix_audio(resolved, theme, storage_root=storage)
        at = resolved["scenes"][1]["sound"][0]["at_s"]
        return decibels(stretch(mixed.effects, at, at + 0.25)) - decibels(mixed.voice)

    assert cue_over_voice(0) - cue_over_voice(-6) == pytest.approx(6.0, abs=0.3)


def test_a_missing_narration_file_names_the_scene(
    resolved: dict[str, Any], theme: Theme, tmp_path: Path
) -> None:
    with pytest.raises(AudioError, match=resolved["scenes"][0]["id"]):
        mix_audio(resolved, theme, storage_root=tmp_path)


def test_a_cue_the_theme_does_not_have_is_named(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    broken = copy.deepcopy(resolved)
    broken["scenes"][1]["sound"][0]["cue_id"] = "thunder"

    with pytest.raises(AudioError, match="thunder"):
        mix_audio(broken, theme, storage_root=storage)


# --- RN-09 -----------------------------------------------------------------------------


def test_rn09_the_voice_is_at_least_10_db_above_the_music_while_speaking(
    mix: AudioMix, resolved: dict[str, Any]
) -> None:
    margins = [
        decibels(stretch(mix.voice, start, end)) - decibels(stretch(mix.music, start, end))
        for start, end in spoken_spans(resolved)
    ]

    assert min(margins) >= 10.0
    assert mix.report.voice_over_music_db == pytest.approx(min(margins), abs=0.5)


def test_rn09_integrated_loudness_is_near_minus_14_lufs(mix: AudioMix) -> None:
    measured = integrated_lufs(mix.samples, SAMPLE_RATE)

    assert measured == pytest.approx(-14.0, abs=0.5)
    assert mix.report.integrated_lufs == pytest.approx(measured, abs=0.05)


def test_rn09_true_peak_stays_under_minus_1_db(mix: AudioMix) -> None:
    measured = true_peak_db(mix.samples, SAMPLE_RATE)

    assert measured < -1.0
    assert mix.report.true_peak_db == pytest.approx(measured, abs=0.05)


def test_the_music_is_down_under_a_voice_and_up_where_the_same_scene_is_silent(
    mix: AudioMix, resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    # The same video and the same music, but the last scene says nothing. Comparing the
    # two at the same moment shows the ducking alone, not the music's own swells.
    spoken = resolved["scenes"][-1]["narration"]
    start, end = spoken["words"][0]["start_s"], spoken["words"][-1]["end_s"]
    without = copy.deepcopy(resolved)
    without["scenes"][-1]["narration"].update(audio_file=None, words=[])

    quiet_scene = mix_audio(without, theme, storage_root=storage)

    under_voice = decibels(stretch(mix.music, start, end))
    nobody_speaking = decibels(stretch(quiet_scene.music, start, end))
    assert under_voice > -60
    assert nobody_speaking - under_voice > 4.0


# --- determinism -------------------------------------------------------------------------


def test_fr11_the_same_spec_gives_the_same_audio(
    mix: AudioMix, resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    again = mix_audio(resolved, theme, storage_root=storage)

    assert np.array_equal(again.samples, mix.samples)


def test_the_seed_changes_the_music_and_nothing_else(
    mix: AudioMix, resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    other = dict(resolved, seed=resolved["seed"] + 1)

    changed = mix_audio(other, theme, storage_root=storage)

    assert not np.array_equal(changed.music, mix.music)
    # The voice is the same recording. Only the final loudness correction moves a little.
    assert decibels(changed.voice) == pytest.approx(decibels(mix.voice), abs=1.0)


def test_a_theme_without_music_mixes_voice_and_effects_only(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    config = {key: value for key, value in theme.config.items() if key != "music"}
    quiet_theme = Theme(**{**theme.__dict__, "config": config})

    mixed = mix_audio(resolved, quiet_theme, storage_root=storage)

    assert not mixed.music.any()
    assert mixed.report.voice_over_music_db is None
    assert integrated_lufs(mixed.samples, SAMPLE_RATE) == pytest.approx(-14.0, abs=0.5)


def test_a_video_without_any_sound_is_silent_not_an_error(theme: Theme, tmp_path: Path) -> None:
    scene = {
        "id": "s01_pause",
        "kind": "title",
        "start_s": 0.0,
        "duration_s": 3.0,
        "narration": {"text": "", "audio_file": None, "start_s": 0.0, "duration_s": 0, "words": []},
        "text": [],
        "overlays": [],
        "sound": [],
    }
    resolved = {"seed": 7, "scenes": [scene]}
    config = {key: value for key, value in theme.config.items() if key != "music"}

    mixed = mix_audio(
        resolved, Theme(**{**theme.__dict__, "config": config}), storage_root=tmp_path
    )

    assert mixed.samples.shape == (3 * SAMPLE_RATE, 2)
    assert not mixed.samples.any()
    assert mixed.report.integrated_lufs == float("-inf")


# --- ducking ---------------------------------------------------------------------------


def test_the_music_is_down_while_someone_speaks_and_up_well_away_from_speech() -> None:
    gain = duck_gain_db([(2.0, 4.0)], 8 * SAMPLE_RATE)

    assert gain[round(3.0 * SAMPLE_RATE)] == 0.0
    assert gain[round(2.0 * SAMPLE_RATE)] == 0.0
    assert gain[round(4.0 * SAMPLE_RATE)] == 0.0
    assert gain[round(0.5 * SAMPLE_RATE)] == OPEN_LIFT_DB
    assert gain[round(7.0 * SAMPLE_RATE)] == OPEN_LIFT_DB


def test_the_music_moves_gradually_never_in_a_jump() -> None:
    gain = duck_gain_db([(2.0, 4.0)], 8 * SAMPLE_RATE)

    # Less than a hundredth of a decibel from one sample to the next.
    assert float(np.abs(np.diff(gain)).max()) < 0.01


def test_a_short_gap_between_two_sentences_stays_down() -> None:
    gain = duck_gain_db([(1.0, 2.0), (2.4, 3.5)], 6 * SAMPLE_RATE)

    assert float(gain[round(1.0 * SAMPLE_RATE) : round(3.5 * SAMPLE_RATE)].max()) == 0.0


def test_without_speech_the_music_stays_up() -> None:
    assert float(duck_gain_db([], SAMPLE_RATE).min()) == OPEN_LIFT_DB


# --- limiter ---------------------------------------------------------------------------


def burst() -> np.ndarray:
    steps = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    quiet = 0.1 * np.sin(2 * np.pi * 300 * steps)
    quiet[20000:20400] += 1.2 * np.sin(2 * np.pi * 900 * steps[:400])
    return np.stack([quiet, quiet], axis=1).astype(np.float32)


def test_the_limiter_holds_every_sample_under_the_ceiling() -> None:
    samples = burst()

    limited = samples * limiter_gain(samples, 0.8)[:, np.newaxis]

    assert float(np.abs(limited).max()) <= 0.8 + 1e-6


def test_the_limiter_leaves_audio_under_the_ceiling_alone() -> None:
    samples = burst()
    gain = limiter_gain(samples, 0.8)

    assert gain[5000] == 1.0
    assert gain[40000] == 1.0
    assert float(limiter_gain(samples * 0.1, 0.8).min()) == 1.0


def test_the_limiter_turns_down_and_up_smoothly() -> None:
    gain = limiter_gain(burst(), 0.8)

    assert float(np.abs(np.diff(gain)).max()) < 0.01


# --- music bed ---------------------------------------------------------------------------


def test_the_music_bed_is_stereo_fades_in_and_out_and_is_never_silent_inside(
    theme: Theme,
) -> None:
    bed = music_bed(theme.config["music"], seed=7, count=10 * SAMPLE_RATE)

    assert bed.shape == (10 * SAMPLE_RATE, 2)
    assert abs(float(bed[0, 0])) < 1e-3
    assert abs(float(bed[-1, 0])) < 1e-3
    for second in range(2, 8):
        assert decibels(bed[second * SAMPLE_RATE : (second + 1) * SAMPLE_RATE]) > -40
    assert not np.array_equal(bed[:, 0], bed[:, 1])


def test_the_music_bed_depends_only_on_its_settings_and_the_seed(theme: Theme) -> None:
    first = music_bed(theme.config["music"], seed=7, count=SAMPLE_RATE)
    second = music_bed(theme.config["music"], seed=7, count=SAMPLE_RATE)
    other = music_bed(theme.config["music"], seed=8, count=SAMPLE_RATE)

    assert np.array_equal(first, second)
    assert not np.array_equal(first, other)


# --- more refusals -----------------------------------------------------------------------


def test_a_narration_file_that_is_not_audio_names_the_scene(
    resolved: dict[str, Any], theme: Theme, tmp_path: Path
) -> None:
    support.sample_voices(tmp_path, resolved)
    first = resolved["scenes"][0]
    (tmp_path / first["narration"]["audio_file"]).write_bytes(b"not audio")

    with pytest.raises(AudioError, match=first["id"]):
        mix_audio(resolved, theme, storage_root=tmp_path)


def test_narration_cannot_be_mixed_without_a_storage_folder(
    resolved: dict[str, Any], theme: Theme
) -> None:
    with pytest.raises(AudioError, match="storage folder"):
        mix_audio(resolved, theme, storage_root=None)


def test_a_cue_before_the_start_or_past_the_end_is_cut_not_an_error(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    edges = copy.deepcopy(resolved)
    last = edges["scenes"][-1]
    edges["scenes"][0]["sound"] = [{"cue_id": "smoke", "at_s": -0.3, "gain_db": 0}]
    last["sound"] = [
        {"cue_id": "smoke", "at_s": last["start_s"] + last["duration_s"] - 0.2, "gain_db": 0}
    ]

    mixed = mix_audio(edges, theme, storage_root=storage)

    assert mixed.samples.shape == (round(mixed.report.duration_s * SAMPLE_RATE), 2)
    assert decibels(stretch(mixed.effects, 0.0, 0.3)) > -60
