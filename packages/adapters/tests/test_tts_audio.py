"""Audio helpers of the voice adapters: WAV in and out, and finding the pauses."""

from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from packages.adapters.tts.audio import find_silences, read_wav, to_wav

RATE = 24000


def tone(seconds: float, level: float = 0.3) -> np.ndarray:
    steps = np.arange(round(seconds * RATE)) / RATE
    return (level * np.sin(2 * np.pi * 220 * steps)).astype(np.float32)


def quiet(seconds: float) -> np.ndarray:
    return np.zeros(round(seconds * RATE), dtype=np.float32)


def test_a_wav_is_mono_16_bit_at_the_given_rate() -> None:
    data = to_wav(tone(0.5), RATE)

    with wave.open(io.BytesIO(data), "rb") as sound:
        assert sound.getnchannels() == 1
        assert sound.getsampwidth() == 2
        assert sound.getframerate() == RATE
        assert sound.getnframes() == RATE // 2


def test_samples_louder_than_full_scale_are_clipped_not_wrapped() -> None:
    samples, _ = read_wav(to_wav(np.array([2.0, -2.0, 0.0], dtype=np.float32), RATE))

    assert samples[0] == pytest.approx(1.0, abs=0.001)
    assert samples[1] == pytest.approx(-1.0, abs=0.001)
    assert samples[2] == 0.0


def test_a_wav_reads_back_as_it_was_written() -> None:
    original = tone(0.25)

    samples, rate = read_wav(to_wav(original, RATE))

    assert rate == RATE
    assert samples.shape == original.shape
    assert float(np.abs(samples - original).max()) < 0.001


def test_something_that_is_not_a_wav_is_refused() -> None:
    with pytest.raises(ValueError, match="WAV"):
        read_wav(b"not audio at all")


def test_the_pauses_before_between_and_after_speech_are_found() -> None:
    samples = np.concatenate([quiet(0.3), tone(1.0), quiet(0.4), tone(0.8), quiet(0.5)])

    silences = find_silences(samples, RATE)

    assert len(silences) == 3
    assert silences[0] == pytest.approx((0.0, 0.3), abs=0.02)
    assert silences[1] == pytest.approx((1.3, 1.7), abs=0.02)
    assert silences[2] == pytest.approx((2.5, 3.0), abs=0.02)


def test_a_gap_too_short_to_be_a_pause_is_ignored() -> None:
    samples = np.concatenate([tone(0.5), quiet(0.04), tone(0.5)])

    assert find_silences(samples, RATE) == []


def test_audio_that_is_silent_throughout_is_one_silence() -> None:
    assert find_silences(quiet(1.0), RATE) == [pytest.approx((0.0, 1.0), abs=0.02)]
