"""Loudness measurement (RN-09): integrated loudness after ITU-R BS.1770 and true peak.

The expected values are the reference cases of EBU Tech 3341 ("EBU Mode" loudness meters):
a meter must read them within 0.1 LU. The same signals are checked with FFmpeg's meter in
the render tests, so the two can never drift apart unnoticed.
"""

from __future__ import annotations

import numpy as np
import pytest

from packages.render.loudness import integrated_lufs, true_peak_db

RATE = 48000


def sine(level_db: float, seconds: float, *, hz: float = 1000.0, phase: float = 0.0) -> np.ndarray:
    """A stereo sine whose peak is `level_db` below full scale, the same in both channels."""
    steps = np.arange(round(seconds * RATE)) / RATE
    mono = 10 ** (level_db / 20) * np.sin(2 * np.pi * hz * steps + phase)
    return np.stack([mono, mono], axis=1).astype(np.float32)


def test_rn09_a_stereo_1khz_sine_at_minus_23_reads_minus_23_lufs() -> None:
    # EBU Tech 3341, case 1.
    assert integrated_lufs(sine(-23.0, 20.0), RATE) == pytest.approx(-23.0, abs=0.1)


def test_rn09_the_same_sine_ten_decibels_lower_reads_ten_lower() -> None:
    # EBU Tech 3341, case 2.
    assert integrated_lufs(sine(-33.0, 20.0), RATE) == pytest.approx(-33.0, abs=0.1)


def test_rn09_quiet_stretches_are_gated_out() -> None:
    # EBU Tech 3341, case 3: 10 s at -36, 60 s at -23, 10 s at -36. The quiet parts fall
    # under the relative gate, so the reading is that of the loud part.
    signal = np.concatenate([sine(-36.0, 10.0), sine(-23.0, 60.0), sine(-36.0, 10.0)])

    assert integrated_lufs(signal, RATE) == pytest.approx(-23.0, abs=0.1)


def test_rn09_silence_between_speech_does_not_lower_the_reading() -> None:
    silence = np.zeros((10 * RATE, 2), dtype=np.float32)
    signal = np.concatenate([sine(-20.0, 10.0), silence, sine(-20.0, 10.0)])

    assert integrated_lufs(signal, RATE) == pytest.approx(
        integrated_lufs(sine(-20.0, 10.0), RATE), abs=0.1
    )


def test_a_mono_signal_reads_three_lower_than_the_same_signal_in_both_channels() -> None:
    stereo = sine(-23.0, 10.0)

    assert integrated_lufs(stereo[:, 0], RATE) == pytest.approx(-26.0, abs=0.1)


def test_low_frequencies_count_less_than_the_ear_weighted_middle() -> None:
    assert (
        integrated_lufs(sine(-23.0, 10.0, hz=50.0), RATE)
        < integrated_lufs(sine(-23.0, 10.0, hz=1000.0), RATE) - 3.0
    )


def test_complete_silence_has_no_loudness() -> None:
    assert integrated_lufs(np.zeros((5 * RATE, 2), dtype=np.float32), RATE) == float("-inf")


def test_audio_shorter_than_one_measuring_block_has_no_loudness() -> None:
    assert integrated_lufs(sine(-23.0, 0.2), RATE) == float("-inf")


def test_rn09_true_peak_finds_the_peak_between_the_samples() -> None:
    # A sine at a quarter of the sample rate, sampled 45 degrees off its peaks: every
    # sample is 3 dB under the real peak of the wave.
    signal = sine(0.0, 1.0, hz=RATE / 4, phase=np.pi / 4)
    sample_peak_db = 20 * np.log10(float(np.abs(signal).max()))

    assert sample_peak_db == pytest.approx(-3.01, abs=0.05)
    assert true_peak_db(signal, RATE) == pytest.approx(0.0, abs=0.1)


def test_true_peak_of_an_ordinary_tone_is_its_level() -> None:
    assert true_peak_db(sine(-6.0, 1.0, hz=440.0), RATE) == pytest.approx(-6.0, abs=0.05)


def test_true_peak_of_silence_is_minus_infinity() -> None:
    assert true_peak_db(np.zeros((RATE, 2), dtype=np.float32), RATE) == float("-inf")


def test_loudness_is_only_measured_at_the_mix_rate() -> None:
    with pytest.raises(ValueError, match="48000"):
        integrated_lufs(np.zeros((44100, 2), dtype=np.float32), 44100)
