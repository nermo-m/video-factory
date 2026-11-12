"""Loudness measurement for the audio mix (RN-09), in NumPy only.

`integrated_lufs` follows ITU-R BS.1770-4: the signal is K-weighted (a shelf that lifts
the highs, as the head does, and a high-pass that drops rumble), its power is averaged in
400 ms blocks that overlap by 75 percent, and blocks that are silent or more than 10 LU
under the average are left out. This is the "integrated loudness" that video platforms
normalise to.

`true_peak_db` is the highest level of the waveform between the samples as well as on
them, found by oversampling four times.

Both are checked against the EBU Tech 3341 reference signals in the unit tests and
against FFmpeg's meter in the render tests.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE = 48000
BLOCK_S = 0.4
HOP_S = 0.1
ABSOLUTE_GATE_LUFS = -70.0
RELATIVE_GATE_LU = -10.0
OVERSAMPLE = 4
_OFFSET_DB = -0.691
# K-weighting filter coefficients for 48 kHz, as printed in ITU-R BS.1770-4, tables 1 and 2.
_SHELF_B = (1.53512485958697, -2.69169618940638, 1.19839281085285)
_SHELF_A = (1.0, -1.69065929318241, 0.73248077421585)
_HIGHPASS_B = (1.0, -2.0, 1.0)
_HIGHPASS_A = (1.0, -1.99004745483398, 0.99007225036621)

Audio = NDArray[np.floating]


def _channels(samples: Audio, sample_rate: int) -> NDArray[np.float64]:
    """Samples as float64 with one column per channel."""
    if sample_rate != SAMPLE_RATE:
        raise ValueError(f"Loudness is measured at {SAMPLE_RATE} Hz, not {sample_rate} Hz.")
    audio = np.asarray(samples, dtype=np.float64)
    return audio.reshape(-1, 1) if audio.ndim == 1 else audio


def _response(
    b: tuple[float, float, float], a: tuple[float, float, float], size: int
) -> NDArray[np.complex128]:
    """The frequency response of a two-pole filter at the bins of a real FFT."""
    z = np.exp(-2j * np.pi * np.arange(size // 2 + 1) / size)
    response = (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return np.asarray(response, dtype=np.complex128)


def k_weighted(samples: Audio, sample_rate: int = SAMPLE_RATE) -> NDArray[np.float64]:
    """The signal after the K-weighting filters of BS.1770, one column per channel."""
    audio = _channels(samples, sample_rate)
    # Filtering in the frequency domain treats the signal as a loop. A second of silence
    # at the end lets the filters ring out there instead of into the start.
    size = len(audio) + SAMPLE_RATE
    response = _response(_SHELF_B, _SHELF_A, size) * _response(_HIGHPASS_B, _HIGHPASS_A, size)
    spectrum = np.fft.rfft(audio, n=size, axis=0) * response[:, np.newaxis]
    weighted: NDArray[np.float64] = np.fft.irfft(spectrum, n=size, axis=0)[: len(audio)]
    return weighted


def _lufs(power: NDArray[np.float64] | float) -> NDArray[np.float64]:
    with np.errstate(divide="ignore"):
        loudness: NDArray[np.float64] = _OFFSET_DB + 10 * np.log10(power)
    return loudness


def integrated_lufs(samples: Audio, sample_rate: int = SAMPLE_RATE) -> float:
    """Integrated loudness in LUFS. Minus infinity for silence or less than one block."""
    weighted = k_weighted(samples, sample_rate)
    block = round(BLOCK_S * SAMPLE_RATE)
    hop = round(HOP_S * SAMPLE_RATE)
    if len(weighted) < block:
        return float("-inf")

    # Power of every block, summed over the channels (left and right count equally).
    running = np.concatenate([np.zeros((1, weighted.shape[1])), np.cumsum(weighted**2, axis=0)])
    starts = np.arange(0, len(weighted) - block + 1, hop)
    power = ((running[starts + block] - running[starts]) / block).sum(axis=1)

    heard = power[_lufs(power) > ABSOLUTE_GATE_LUFS]
    if heard.size == 0:
        return float("-inf")
    relative_gate = float(_lufs(heard.mean())) + RELATIVE_GATE_LU
    counted = heard[_lufs(heard) > relative_gate]
    return float(_lufs(counted.mean()))


def true_peak_db(samples: Audio, sample_rate: int = SAMPLE_RATE) -> float:
    """The true peak in dB relative to full scale. Minus infinity for silence."""
    audio = _channels(samples, sample_rate)
    peak = 0.0
    for channel in audio.T:
        # Four times as many samples from the same spectrum: the wave between the samples.
        spectrum = np.fft.rfft(channel)
        fine = np.fft.irfft(spectrum, n=len(channel) * OVERSAMPLE) * OVERSAMPLE
        peak = max(peak, float(np.abs(fine).max()), float(np.abs(channel).max()))
    if peak == 0.0:
        return float("-inf")
    return float(20 * np.log10(peak))
