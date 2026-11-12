"""WAV files and sample-rate conversion for the audio mix."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from packages.render.wav import read_wav, resample, write_wav


def tone(rate: int, seconds: float, hz: float = 440.0, level: float = 0.5) -> np.ndarray:
    steps = np.arange(round(seconds * rate)) / rate
    return (level * np.sin(2 * np.pi * hz * steps)).astype(np.float32)


def test_a_stereo_file_reads_back_as_it_was_written(tmp_path: Path) -> None:
    left, right = tone(48000, 0.5), tone(48000, 0.5, hz=660.0)
    samples = np.stack([left, right], axis=1)

    write_wav(tmp_path / "mix.wav", samples, 48000)
    loaded, rate = read_wav(tmp_path / "mix.wav")

    assert rate == 48000
    assert loaded.shape == samples.shape
    assert float(np.abs(loaded - samples).max()) < 0.0001


def test_a_written_file_is_16_bit_pcm(tmp_path: Path) -> None:
    write_wav(tmp_path / "mix.wav", np.stack([tone(48000, 0.1)] * 2, axis=1), 48000)

    with wave.open(str(tmp_path / "mix.wav"), "rb") as sound:
        assert (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()) == (2, 2, 48000)


def test_a_mono_file_reads_as_one_column(tmp_path: Path) -> None:
    write_wav(tmp_path / "voice.wav", tone(24000, 0.25), 24000)

    loaded, rate = read_wav(tmp_path / "voice.wav")

    assert rate == 24000
    assert loaded.shape == (6000, 1)


def test_samples_beyond_full_scale_are_clipped(tmp_path: Path) -> None:
    write_wav(tmp_path / "loud.wav", np.array([1.5, -1.5], dtype=np.float32), 48000)

    loaded, _ = read_wav(tmp_path / "loud.wav")

    assert loaded[:, 0].tolist() == pytest.approx([1.0, -1.0], abs=0.0001)


def test_a_file_that_is_not_a_wav_is_refused(tmp_path: Path) -> None:
    (tmp_path / "broken.wav").write_bytes(b"not a wav")

    with pytest.raises(ValueError, match=r"broken\.wav"):
        read_wav(tmp_path / "broken.wav")


def test_doubling_the_rate_doubles_the_samples_and_keeps_the_tone() -> None:
    voice = tone(24000, 1.0)

    converted = resample(voice, 24000, 48000)

    assert converted.shape == (48000,)
    # Same pitch and same level: it still matches a 440 Hz tone made at the new rate.
    assert float(np.abs(converted - tone(48000, 1.0)).max()) < 0.01


def test_a_cd_rate_sound_is_converted_to_the_video_rate() -> None:
    sound = tone(44100, 0.5, hz=1000.0)

    converted = resample(sound, 44100, 48000)

    assert converted.shape == (24000,)
    spectrum = np.abs(np.fft.rfft(converted))
    assert np.fft.rfftfreq(24000, 1 / 48000)[int(spectrum.argmax())] == pytest.approx(
        1000.0, abs=2.0
    )
    assert float(np.sqrt((converted**2).mean())) == pytest.approx(0.5 / np.sqrt(2), rel=0.02)


def test_audio_already_at_the_right_rate_is_left_alone() -> None:
    sound = tone(48000, 0.1)

    assert resample(sound, 48000, 48000) is sound


def test_audio_that_is_not_16_bit_is_refused(tmp_path: Path) -> None:
    with wave.open(str(tmp_path / "eight.wav"), "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(1)
        sound.setframerate(8000)
        sound.writeframes(b"\x80" * 100)

    with pytest.raises(ValueError, match="16-bit"):
        read_wav(tmp_path / "eight.wav")
