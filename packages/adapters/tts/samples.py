"""The voice adapter's twin: bundled sample audio (design doc section 3.3).

Kokoro needs no key and no GPU, so the real voice is also the demo voice. Its model files
are a 340 MB download, though. When they are missing, this adapter returns narration that
was recorded earlier with the real voice and stored in the repository, so demo mode and
CI work on any machine. Narration with no recording is refused with the command that
downloads the model.

A recording is found by a key made from the narration text, the voice, the speed and the
dictionary words the narration uses. Word timings are estimated from the recording's audio
exactly as for the real voice.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from packages.adapters.tts.audio import find_silences, read_wav
from packages.adapters.tts.base import Narration, VoiceError
from packages.adapters.tts.pronunciation import MARKS
from packages.adapters.tts.timings import estimate_word_timings

_KEY_LENGTH = 20


def sample_key(
    text: str,
    *,
    voice_id: str,
    speed: float,
    pronunciation: Mapping[str, str] | None = None,
) -> str:
    """The name under which the recording for this request is stored."""
    words = {word.strip(MARKS).casefold() for word in text.split()}
    used = sorted(
        (word.casefold(), phonemes.strip())
        for word, phonemes in (pronunciation or {}).items()
        if word.casefold() in words
    )
    request = json.dumps(
        [" ".join(text.split()), voice_id, f"{speed:.2f}", used], ensure_ascii=False
    )
    return hashlib.sha256(request.encode("utf-8")).hexdigest()[:_KEY_LENGTH]


def write_sample(
    folder: Path,
    narration: Narration,
    *,
    text: str,
    voice_id: str,
    speed: float,
    pronunciation: Mapping[str, str] | None = None,
) -> Path:
    """Store a narration made by the real voice as a bundled sample. Returns its file."""
    folder.mkdir(parents=True, exist_ok=True)
    key = sample_key(text, voice_id=voice_id, speed=speed, pronunciation=pronunciation)
    path = folder / f"{key}.wav"
    path.write_bytes(narration.wav)
    return path


class SampleVoice:
    """TTSAdapter that returns bundled recordings."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def synthesise(
        self,
        text: str,
        *,
        voice_id: str,
        speed: float = 1.0,
        pronunciation: Mapping[str, str] | None = None,
    ) -> Narration:
        key = sample_key(text, voice_id=voice_id, speed=speed, pronunciation=pronunciation)
        path = self.folder / f"{key}.wav"
        if not path.is_file():
            raise VoiceError(
                "The voice model files are missing and there is no bundled sample for this "
                "narration. Download the voice model with: make models"
            )
        wav = path.read_bytes()
        try:
            samples, sample_rate = read_wav(wav)
        except ValueError as error:
            raise VoiceError(f"The bundled sample {path.name} cannot be read: {error}") from error
        duration_s = len(samples) / sample_rate
        return Narration(
            wav=wav,
            sample_rate=sample_rate,
            duration_s=duration_s,
            words=estimate_word_timings(text, duration_s, find_silences(samples, sample_rate)),
            engine="sample",
        )
