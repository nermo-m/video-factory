"""WAV files and sample-rate conversion for the audio mix.

Only what the render engine needs: 16-bit PCM, mono or stereo. Samples are float32 in the
range -1 to 1, one column per channel.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

Samples = NDArray[np.float32]
_FULL_SCALE = 32767


def read_wav(path: Path) -> tuple[Samples, int]:
    """Read a 16-bit WAV file as (samples with one column per channel, sample rate)."""
    try:
        with wave.open(str(path), "rb") as sound:
            if sound.getsampwidth() != 2:
                raise ValueError(f"{path.name} is not 16-bit audio.")
            channels = sound.getnchannels()
            rate = sound.getframerate()
            frames = sound.readframes(sound.getnframes())
    except (wave.Error, EOFError) as error:
        raise ValueError(f"{path.name} is not a WAV file: {error}") from error
    samples = (np.frombuffer(frames, dtype="<i2") / _FULL_SCALE).astype(np.float32)
    return samples.reshape(-1, channels), rate


def write_wav(path: Path, samples: NDArray[np.floating], sample_rate: int) -> None:
    """Write samples as 16-bit PCM. A flat array is mono, columns are channels."""
    audio = np.asarray(samples)
    channels = 1 if audio.ndim == 1 else audio.shape[1]
    pcm = np.round(np.clip(audio, -1.0, 1.0) * _FULL_SCALE).astype("<i2")
    with wave.open(str(path), "wb") as sound:
        sound.setnchannels(channels)
        sound.setsampwidth(2)
        sound.setframerate(sample_rate)
        sound.writeframes(pcm.tobytes())


def resample(samples: Samples, from_rate: int, to_rate: int) -> Samples:
    """Convert audio to another sample rate, keeping its pitch, level and length in time.

    The conversion is done on the spectrum: the same frequencies, written out with more
    or fewer samples. That is exact for the short clips the mix places (a scene's
    narration, a sound cue), and it needs no filter design.
    """
    if from_rate == to_rate:
        return samples
    length = round(len(samples) * to_rate / from_rate)
    spectrum = np.fft.rfft(samples, axis=0)
    converted = np.fft.irfft(spectrum, n=length, axis=0) * (length / len(samples))
    return converted.astype(np.float32)
