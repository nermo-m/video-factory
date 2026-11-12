"""Audio mix (design doc section 7.1, RN-09).

Builds the sound of a video from its resolved spec, as three stems that add up to the mix:

* voice: each scene's narration file, placed at its resolved time;
* effects: the theme's sound cues, at their resolved times, with their `gain_db`;
* music: a bed synthesised from the theme's settings and the spec's seed, turned down
  while someone speaks (ducking).

The mix is then brought to -14 LUFS integrated loudness, and a limiter keeps the true peak
under -1 dB. Output is 48 kHz stereo and exactly as long as the video.

Levels are set from the voice. The music under speech sits VOICE_OVER_MUSIC_DB below the
quietest scene's voice, so the 10 dB of RN-09 hold with room to spare. Like the
compositor, this module has no clock and no unseeded randomness: the same resolved spec
gives the same samples.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from packages.render.loudness import integrated_lufs, true_peak_db
from packages.render.primitives import seeded
from packages.render.theme import Theme
from packages.render.timeline import build_timeline
from packages.render.wav import read_wav, resample

SAMPLE_RATE = 48000
TARGET_LUFS = -14.0
TRUE_PEAK_LIMIT_DB = -1.0
# The limiter aims a little under the limit, because the peak between samples can be
# higher than the samples themselves.
_FIRST_CEILING_DB = -1.6
_LOUDNESS_TOLERANCE_LU = 0.2
_MAX_ROUNDS = 6

# Music under speech, relative to the voice. RN-09 asks for at least 10 dB.
VOICE_OVER_MUSIC_DB = 14.0
# How far the music comes up when nobody speaks.
OPEN_LIFT_DB = 6.0
DUCK_ATTACK_S = 0.3  # the music is fully down this long before the first word...
DUCK_LEAD_S = 0.05  # ...and has finished moving this long before it
DUCK_HOLD_S = 0.1  # it stays down this long after the last word
DUCK_RELEASE_S = 0.5  # and takes this long to come back up
# Pauses shorter than this do not bring the music up. It would pump.
DUCK_MERGE_GAP_S = DUCK_ATTACK_S + DUCK_LEAD_S + DUCK_HOLD_S + DUCK_RELEASE_S

# A sound cue's loudest sample, relative to the voice's average level, at gain_db 0.
CUE_PEAK_OVER_VOICE_DB = 6.0
# Used for cue and music levels when a video has no narration at all.
_REFERENCE_VOICE_DB = -20.0

MUSIC_FADE_IN_S = 1.0
MUSIC_FADE_OUT_S = 1.0
_DETUNE = 0.0015
_DRIFT_HZ = (0.04, 0.12)

_LIMITER_BLOCK = 48  # one millisecond
_LIMITER_REACH = 5  # blocks the limiter looks ahead and behind

Audio = NDArray[np.float32]
Span = tuple[float, float]


class AudioError(Exception):
    """The audio cannot be mixed. The message says what is missing."""


@dataclass(frozen=True)
class AudioReport:
    """What was measured on the finished mix."""

    duration_s: float
    integrated_lufs: float
    true_peak_db: float
    # The smallest margin of any spoken scene. None without narration or without music.
    voice_over_music_db: float | None


@dataclass(frozen=True)
class AudioMix:
    """The finished audio and its three stems. All are 48 kHz stereo and the same length."""

    samples: Audio
    voice: Audio
    effects: Audio
    music: Audio
    report: AudioReport
    sample_rate: int = SAMPLE_RATE


# --- public ------------------------------------------------------------------------------


def mix_audio(resolved: Mapping[str, Any], theme: Theme, *, storage_root: Path | None) -> AudioMix:
    """Mix the audio of a resolved spec. Raises AudioError when a file or cue is missing."""
    scenes = resolved["scenes"]
    duration_s = scenes[-1]["start_s"] + scenes[-1]["duration_s"]
    count = round(duration_s * SAMPLE_RATE)
    events = build_timeline(resolved)

    voice = np.zeros(count, dtype=np.float32)
    for event in events:
        if event.kind == "narration":
            clip = _narration(event.data["audio_file"], scenes[event.scene]["id"], storage_root)
            _place(voice, clip, event.at_s)
    spans = _spoken_spans(scenes)
    voice_levels = [_level_db(_cut(voice, start, end)) for start, end in spans]
    heard = [level for level in voice_levels if level > float("-inf")]
    voice_db = min(heard) if heard else _REFERENCE_VOICE_DB

    effects = np.zeros(count, dtype=np.float32)
    cues: dict[str, Audio] = {}
    for event in events:
        if event.kind == "sound":
            cue_id = event.data["cue_id"]
            if cue_id not in cues:
                cues[cue_id] = _cue(cue_id, theme)
            peak_db = voice_db + CUE_PEAK_OVER_VOICE_DB + event.data.get("gain_db", 0)
            _place(effects, cues[cue_id] * _linear(peak_db), event.at_s)

    music = np.zeros((count, 2), dtype=np.float32)
    settings = theme.config.get("music")
    if settings and count:
        bed = music_bed(settings, resolved["seed"], count)
        under_voice_db = voice_db - VOICE_OVER_MUSIC_DB
        lift = _linear(duck_gain_db(spans, count))
        music = (bed * _linear(under_voice_db - _level_db(bed)) * lift[:, np.newaxis]).astype(
            np.float32
        )

    stems = [np.stack([voice, voice], axis=1), np.stack([effects, effects], axis=1), music]
    gain = _mastering_gain(stems[0] + stems[1] + stems[2])
    voice_out, effects_out, music_out = (
        (stem * gain[:, np.newaxis]).astype(np.float32) for stem in stems
    )
    samples = (voice_out + effects_out + music_out).astype(np.float32)

    margins = [
        _level_db(_cut(voice_out, start, end)) - _level_db(_cut(music_out, start, end))
        for start, end in spans
        if _cut(voice_out, start, end).any() and _cut(music_out, start, end).any()
    ]
    return AudioMix(
        samples=samples,
        voice=voice_out,
        effects=effects_out,
        music=music_out,
        report=AudioReport(
            duration_s=count / SAMPLE_RATE,
            integrated_lufs=integrated_lufs(samples, SAMPLE_RATE),
            true_peak_db=true_peak_db(samples, SAMPLE_RATE),
            voice_over_music_db=min(margins) if margins else None,
        ),
    )


def duck_gain_db(spans: Sequence[Span], count: int) -> NDArray[np.float64]:
    """How far the music is lifted at every sample, in dB: 0 under speech, OPEN_LIFT_DB
    when nobody speaks, and a straight ramp in between."""
    merged: list[list[float]] = []
    for start, end in sorted(spans):
        if merged and start - merged[-1][1] < DUCK_MERGE_GAP_S:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    times: list[float] = []
    values: list[float] = []
    for start, end in merged:
        times += [
            start - DUCK_ATTACK_S - DUCK_LEAD_S,
            start - DUCK_LEAD_S,
            end + DUCK_HOLD_S,
            end + DUCK_HOLD_S + DUCK_RELEASE_S,
        ]
        values += [OPEN_LIFT_DB, 0.0, 0.0, OPEN_LIFT_DB]
    if not times:
        return np.full(count, OPEN_LIFT_DB)
    return np.interp(np.arange(count) / SAMPLE_RATE, times, values)


def limiter_gain(samples: NDArray[np.floating], ceiling: float) -> NDArray[np.float64]:
    """A gain for every sample that keeps the audio under `ceiling` (0 to 1).

    The gain is 1 wherever the audio is under the ceiling anyway. Before a peak it turns
    down over a few milliseconds and comes back as slowly, so the correction is not heard
    as a click.
    """
    peak = np.abs(samples).max(axis=1) if samples.ndim == 2 else np.abs(samples)
    count = len(peak)
    blocks = -(-count // _LIMITER_BLOCK)
    padded = np.zeros(blocks * _LIMITER_BLOCK)
    padded[:count] = peak
    block_peak = padded.reshape(blocks, _LIMITER_BLOCK).max(axis=1)
    needed = np.minimum(1.0, ceiling / np.maximum(block_peak, 1e-12))

    # The lowest gain needed anywhere within reach, twice as wide as the smoothing that
    # follows, so the smoothed gain is never above what a block needs.
    reach = 2 * _LIMITER_REACH
    wide = np.pad(needed, reach, constant_values=1.0)
    lowest = np.lib.stride_tricks.sliding_window_view(wide, 2 * reach + 1).min(axis=1)
    window = np.hanning(2 * _LIMITER_REACH + 3)[1:-1]
    smooth = np.convolve(
        np.pad(lowest, _LIMITER_REACH, mode="edge"), window / window.sum(), mode="valid"
    )
    # Averaging ones can give a value a hair under one. Untouched audio stays untouched.
    smooth[smooth > 1.0 - 1e-9] = 1.0

    centres = (np.arange(blocks) + 0.5) * _LIMITER_BLOCK
    gain = np.interp(np.arange(count), centres, smooth)
    # Straight lines between block centres can sit a hair above what a sample needs.
    exact: NDArray[np.float64] = np.minimum(
        gain, np.minimum(1.0, ceiling / np.maximum(peak, 1e-12))
    )
    return exact


def music_bed(settings: Mapping[str, Any], seed: int, count: int) -> Audio:
    """A soft sustained chord for the whole video, stereo, from the theme's settings.

    `settings["notes_hz"]` are the notes of the chord and `settings["brightness"]` (0 to 1)
    how much of each note's overtones is heard. Every note swells and fades slowly on its
    own, differently in each channel, so the bed moves without a beat or a loop. The seed
    decides the swells.
    """
    random = seeded(seed, "music")
    steps = np.arange(count) / SAMPLE_RATE
    brightness = float(settings.get("brightness", 0.3))
    bed = np.zeros((count, 2))
    for position, note in enumerate(settings["notes_hz"]):
        tone = np.zeros(count)
        for harmonic in (1, 2, 3):
            strength = brightness ** (harmonic - 1) / harmonic
            for detune in (1 - _DETUNE, 1 + _DETUNE):
                phase = random.uniform(0, 2 * np.pi)
                tone += strength * np.sin(2 * np.pi * note * harmonic * detune * steps + phase)
        for channel in (0, 1):
            drift = random.uniform(*_DRIFT_HZ)
            phase = random.uniform(0, 2 * np.pi)
            swell = 0.7 + 0.3 * np.sin(2 * np.pi * drift * steps + phase)
            bed[:, channel] += tone * swell / np.sqrt(position + 1)

    fade_in = min(round(MUSIC_FADE_IN_S * SAMPLE_RATE), count // 2)
    fade_out = min(round(MUSIC_FADE_OUT_S * SAMPLE_RATE), count // 2)
    if fade_in:
        bed[:fade_in] *= np.sin(np.linspace(0, np.pi / 2, fade_in))[:, np.newaxis] ** 2
    if fade_out:
        bed[-fade_out:] *= np.cos(np.linspace(0, np.pi / 2, fade_out))[:, np.newaxis] ** 2
    loudest = float(np.abs(bed).max())
    return (bed / loudest * 0.5).astype(np.float32) if loudest else bed.astype(np.float32)


# --- steps -------------------------------------------------------------------------------


def _linear(decibels: Any) -> Any:
    return 10 ** (np.asarray(decibels, dtype=np.float64) / 20)


def _level_db(samples: NDArray[np.floating]) -> float:
    """Average level (root mean square) in dB relative to full scale."""
    if samples.size == 0:
        return float("-inf")
    power = float((np.asarray(samples, dtype=np.float64) ** 2).mean())
    return 10 * float(np.log10(power)) if power > 0 else float("-inf")


def _cut(samples: NDArray[np.floating], start_s: float, end_s: float) -> NDArray[np.floating]:
    return samples[max(0, round(start_s * SAMPLE_RATE)) : max(0, round(end_s * SAMPLE_RATE))]


def _place(track: Audio, clip: Audio, at_s: float) -> None:
    """Add a clip to a track at a time. What falls outside the track is dropped."""
    start = round(at_s * SAMPLE_RATE)
    if start < 0:
        clip, start = clip[-start:], 0
    clip = clip[: max(0, len(track) - start)]
    track[start : start + len(clip)] += clip


def _mono_at_mix_rate(path: Path) -> Audio:
    samples, rate = read_wav(path)
    return resample(samples.mean(axis=1).astype(np.float32), rate, SAMPLE_RATE)


def _narration(audio_file: str, scene_id: str, storage_root: Path | None) -> Audio:
    if storage_root is None:
        raise AudioError("No storage folder was given, so narration files cannot be read.")
    path = storage_root / audio_file
    if not path.is_file():
        raise AudioError(f"The narration file for scene '{scene_id}' is missing: {audio_file}")
    try:
        return _mono_at_mix_rate(path)
    except ValueError as error:
        raise AudioError(f"The narration for scene '{scene_id}' cannot be read: {error}") from error


def _cue(cue_id: str, theme: Theme) -> Audio:
    """A theme sound cue, scaled so its loudest sample is at full scale."""
    path = theme.sounds.get(cue_id)
    if path is None or not path.is_file():
        raise AudioError(
            f"The theme '{theme.name}' has no sound cue '{cue_id}'. "
            f"It has: {', '.join(sorted(theme.sounds))}"
        )
    clip = _mono_at_mix_rate(path)
    loudest = float(np.abs(clip).max())
    return (clip / loudest).astype(np.float32) if loudest else clip


def _spoken_spans(scenes: Sequence[Mapping[str, Any]]) -> list[Span]:
    """From the first word to the last word of every spoken scene."""
    return [
        (scene["narration"]["words"][0]["start_s"], scene["narration"]["words"][-1]["end_s"])
        for scene in scenes
        if scene["narration"]["audio_file"] and scene["narration"]["words"]
    ]


def _mastering_gain(mix: NDArray[np.floating]) -> NDArray[np.float64]:
    """One gain per sample that brings the mix to the target loudness and peak limit.

    Loudness first, then the limiter. Limiting takes a little loudness away and can leave
    a peak between samples above the limit, so both are measured again and corrected,
    until the mix is inside both limits.
    """
    gain = np.ones(len(mix))
    if integrated_lufs(mix, SAMPLE_RATE) == float("-inf"):
        return gain
    level_db = 0.0
    ceiling_db = _FIRST_CEILING_DB
    for _ in range(_MAX_ROUNDS):
        scaled = mix * _linear(level_db)
        gain = _linear(level_db) * limiter_gain(scaled, float(_linear(ceiling_db)))
        mastered = mix * gain[:, np.newaxis]
        loudness = integrated_lufs(mastered, SAMPLE_RATE)
        peak_db = true_peak_db(mastered, SAMPLE_RATE)
        loud_enough = abs(loudness - TARGET_LUFS) <= _LOUDNESS_TOLERANCE_LU
        if loud_enough and peak_db < TRUE_PEAK_LIMIT_DB - 0.05:
            break
        if peak_db >= TRUE_PEAK_LIMIT_DB - 0.05:
            ceiling_db -= peak_db - (TRUE_PEAK_LIMIT_DB - 0.2)
        level_db += TARGET_LUFS - loudness
    return gain
