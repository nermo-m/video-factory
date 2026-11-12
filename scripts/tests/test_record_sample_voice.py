"""`make sample-voice`: recording the sample narration for machines without the voice model."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pytest

from apps.worker.demo_render import load_sample
from packages.adapters.tts.audio import to_wav
from packages.adapters.tts.base import Narration, VoiceError
from packages.adapters.tts.samples import SampleVoice
from packages.adapters.tts.timings import estimate_word_timings
from scripts.record_sample_voice import record


class FakeVoice:
    """Answers like the real voice, or like the bundled one, with a second of tone."""

    def __init__(self, engine: str = "kokoro") -> None:
        self.engine = engine
        self.spoken: list[str] = []

    def synthesise(
        self,
        text: str,
        *,
        voice_id: str,
        speed: float = 1.0,
        pronunciation: Mapping[str, str] | None = None,
    ) -> Narration:
        self.spoken.append(text)
        steps = np.arange(24000) / 24000
        samples = (0.3 * np.sin(2 * np.pi * 200 * steps)).astype(np.float32)
        return Narration(
            wav=to_wav(samples, 24000),
            sample_rate=24000,
            duration_s=1.0,
            words=estimate_word_timings(text, 1.0),
            engine=self.engine,
        )


def test_every_scene_is_recorded_and_can_be_played_back_by_the_bundled_voice(
    tmp_path: Path,
) -> None:
    authored = load_sample()
    voice = FakeVoice()

    written = record(voice, tmp_path)

    assert voice.spoken == [scene["narration"] for scene in authored["scenes"]]
    assert len(written) == len(authored["scenes"])
    playback = SampleVoice(tmp_path).synthesise(
        authored["scenes"][0]["narration"],
        voice_id=authored["voice"]["voice_id"],
        speed=authored["voice"]["speed"],
    )
    assert playback.duration_s == pytest.approx(1.0)


def test_recordings_of_lines_that_no_longer_exist_are_removed(tmp_path: Path) -> None:
    old = tmp_path / "0123456789abcdef0123.wav"
    old.write_bytes(b"an old take")
    notes = tmp_path / "notes.txt"
    notes.write_text("not a recording", encoding="utf-8")

    written = record(FakeVoice(), tmp_path)

    assert not old.exists()
    assert notes.exists()
    assert sorted(tmp_path.glob("*.wav")) == sorted(written)


def test_the_bundled_voice_cannot_record_itself(tmp_path: Path) -> None:
    with pytest.raises(VoiceError, match="make models"):
        record(FakeVoice(engine="sample"), tmp_path)
