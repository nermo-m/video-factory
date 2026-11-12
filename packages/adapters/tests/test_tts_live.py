"""The real Kokoro voice, run with the real model files (design doc 14.1, level "Live").

These tests are marked `voice` and are not part of `make test`. They need the model files
from `make models` and the espeak-ng program, so they run inside the worker image:

    make models
    make voice-test

They exist because the adapter's unit tests use a stand-in for the model. This file is the
proof that the token table, the phoneme alphabet and the pause detection match the real
tool (build rule 10).
"""

from __future__ import annotations

import io
import os
import wave
from pathlib import Path

import pytest

from packages.adapters.tts import create_tts_adapter
from packages.adapters.tts.base import TTSAdapter
from packages.adapters.tts.kokoro import SAMPLE_RATE, KokoroVoice

pytestmark = pytest.mark.voice

MODEL = Path(os.environ.get("KOKORO_MODEL_PATH", "models/kokoro/kokoro.onnx"))
VOICES = Path(os.environ.get("KOKORO_VOICES_PATH", "models/kokoro/voices.bin"))
TEXT = "The keeper climbed the same hill every morning. Nobody asked him to."


@pytest.fixture(scope="module")
def voice() -> TTSAdapter:
    adapter = create_tts_adapter(MODEL, VOICES)
    assert isinstance(adapter, KokoroVoice), (
        f"The voice model files are not at {MODEL} and {VOICES}. Run: make models"
    )
    return adapter


def test_fr10_the_real_voice_speaks_a_scene_at_a_natural_pace(voice: TTSAdapter) -> None:
    narration = voice.synthesise(TEXT, voice_id="bm_george")

    with wave.open(io.BytesIO(narration.wav), "rb") as sound:
        assert sound.getframerate() == SAMPLE_RATE
        assert sound.getnchannels() == 1
        loudest = max(abs(sample) for sample in memoryview(sound.readframes(10**9)).cast("h"))
    # Twelve words take three to seven seconds, and the audio is not silence.
    assert 3.0 < narration.duration_s < 7.0
    assert loudest > 3000


def test_fr10_word_timings_follow_the_pause_between_the_sentences(voice: TTSAdapter) -> None:
    narration = voice.synthesise(TEXT, voice_id="bm_george")
    words = narration.words

    assert [word.text for word in words] == TEXT.split()
    # The voice starts after a short lead-in and stops before the end of the file.
    assert 0.05 < words[0].start_s < 0.8
    assert words[-1].end_s < narration.duration_s
    # "morning." ends one sentence and "Nobody" starts the next: the measured pause sits
    # between them, and the first sentence, with eight of the twelve words, takes most
    # of the time.
    pause = words[8].start_s - words[7].end_s
    assert 0.15 < pause < 1.0
    assert 0.5 < words[7].end_s / narration.duration_s < 0.8


def test_the_same_request_gives_the_same_audio(voice: TTSAdapter) -> None:
    first = voice.synthesise("Small steps still count.", voice_id="bm_george")
    second = voice.synthesise("Small steps still count.", voice_id="bm_george")

    assert first.wav == second.wav


def test_a_faster_speed_gives_shorter_audio(voice: TTSAdapter) -> None:
    normal = voice.synthesise("Small steps still count.", voice_id="af_heart")
    fast = voice.synthesise("Small steps still count.", voice_id="af_heart", speed=1.4)

    assert fast.duration_s < normal.duration_s * 0.9


def test_fr10_a_dictionary_word_is_spoken_from_its_phonemes(voice: TTSAdapter) -> None:
    plain = voice.synthesise("Ask Nermin today.", voice_id="bm_george")
    taught = voice.synthesise(
        "Ask Nermin today.", voice_id="bm_george", pronunciation={"Nermin": "nˈɛɹmiːn"}
    )

    assert taught.wav != plain.wav
    assert [word.text for word in taught.words] == ["Ask", "Nermin", "today."]
    assert 0.8 < taught.duration_s < 4.0
