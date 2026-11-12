"""Voice adapters: the Kokoro voice and its bundled-sample twin (design doc section 3.3)."""

from __future__ import annotations

from pathlib import Path

from packages.adapters.tts.base import Narration, TTSAdapter, VoiceError
from packages.adapters.tts.kokoro import KokoroVoice
from packages.adapters.tts.samples import SampleVoice

__all__ = ["Narration", "TTSAdapter", "VoiceError", "create_tts_adapter"]

# Recordings of the sample episode's narration, made with the real voice.
DEFAULT_SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples" / "voice"


def create_tts_adapter(
    model_path: Path, voices_path: Path, *, samples_dir: Path = DEFAULT_SAMPLES_DIR
) -> TTSAdapter:
    """The real voice when both model files are present, bundled samples otherwise."""
    if model_path.is_file() and voices_path.is_file():
        return KokoroVoice(model_path, voices_path)
    return SampleVoice(samples_dir)
