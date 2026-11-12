"""Audio helpers for the voice adapters: WAV in and out, and finding the pauses."""

from __future__ import annotations

import io
import wave

import numpy as np
from numpy.typing import NDArray

Samples = NDArray[np.float32]
Span = tuple[float, float]

_FULL_SCALE = 32767
_WINDOW_S = 0.01
# Measured on Kokoro output: between words the level stays above this, in a pause it
# falls well below it.
SILENCE_LEVEL = 0.01
MIN_SILENCE_S = 0.08


def to_wav(samples: Samples, sample_rate: int) -> bytes:
    """Encode samples in the range -1 to 1 as a mono 16-bit WAV file."""
    pcm = np.round(np.clip(samples, -1.0, 1.0) * _FULL_SCALE).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(sample_rate)
        sound.writeframes(pcm.tobytes())
    return buffer.getvalue()


def read_wav(data: bytes) -> tuple[Samples, int]:
    """Decode a mono 16-bit WAV file into samples in the range -1 to 1 and its rate."""
    try:
        with wave.open(io.BytesIO(data), "rb") as sound:
            if sound.getnchannels() != 1 or sound.getsampwidth() != 2:
                raise ValueError("Only mono 16-bit WAV files are supported.")
            frames = sound.readframes(sound.getnframes())
            rate = sound.getframerate()
    except (wave.Error, EOFError) as error:
        raise ValueError(f"This is not a WAV file: {error}") from error
    samples = (np.frombuffer(frames, dtype="<i2") / _FULL_SCALE).astype(np.float32)
    return samples, rate


def find_silences(
    samples: Samples,
    sample_rate: int,
    *,
    level: float = SILENCE_LEVEL,
    min_s: float = MIN_SILENCE_S,
) -> list[Span]:
    """The quiet stretches of at least `min_s` seconds, as (start, end) in seconds."""
    window = max(1, round(sample_rate * _WINDOW_S))
    count = len(samples) // window
    if count == 0:
        return []
    duration = len(samples) / sample_rate
    loudness = np.sqrt(
        (samples[: count * window].reshape(count, window).astype(np.float64) ** 2).mean(axis=1)
    )
    quiet = loudness < level

    silences: list[Span] = []
    start: int | None = None
    for index in range(count + 1):
        if index < count and quiet[index]:
            if start is None:
                start = index
            continue
        if start is not None:
            begin = start * window / sample_rate
            end = duration if index == count else index * window / sample_rate
            if end - begin >= min_s:
                silences.append((begin, end))
            start = None
    return silences
