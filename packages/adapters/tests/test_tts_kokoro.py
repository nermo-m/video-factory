"""The Kokoro voice adapter (FR-10), checked against a stand-in for the model.

The stand-in has the same inputs and output as the real model file: `tokens`, `style` and
`speed` in, audio samples out. The real model is checked in test_tts_live.py.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from packages.adapters.tts.base import VoiceError
from packages.adapters.tts.kokoro import MAX_TOKENS, SAMPLE_RATE, KokoroVoice, load_vocabulary

VOCAB = load_vocabulary()


class FakeModel:
    """Answers like the model file: 0.2 s of quiet, speech, 0.2 s of quiet."""

    def __init__(self) -> None:
        self.runs: list[dict[str, np.ndarray]] = []

    def run(self, output_names: Any, inputs: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.runs.append(inputs)
        spoken = inputs["tokens"].shape[1] * 0.05
        steps = np.arange(round(spoken * SAMPLE_RATE)) / SAMPLE_RATE
        quiet = np.zeros(round(0.2 * SAMPLE_RATE), dtype=np.float32)
        speech = (0.3 * np.sin(2 * np.pi * 180 * steps)).astype(np.float32)
        return [np.concatenate([quiet, speech, quiet])]


def letters_as_phonemes(text: str, *, british: bool) -> str:
    """A stand-in for espeak-ng: lower-case letters are valid phonemes."""
    return text.lower()


def voice_table() -> dict[str, np.ndarray]:
    # Row n of a voice holds the number n, so a test can see which row was picked.
    rows = np.arange(510, dtype=np.float32).reshape(510, 1, 1) * np.ones((1, 1, 256), np.float32)
    return {"bm_george": rows, "af_heart": rows + 1000, "jf_alpha": rows}


@pytest.fixture
def model() -> FakeModel:
    return FakeModel()


@pytest.fixture
def voice(model: FakeModel) -> KokoroVoice:
    return KokoroVoice(
        Path("unused.onnx"),
        Path("unused.bin"),
        phonemise=letters_as_phonemes,
        session=model,
        voices=voice_table(),
    )


def test_fr10_a_scene_is_spoken_as_one_passage(voice: KokoroVoice, model: FakeModel) -> None:
    voice.synthesise("Small steps. They still count.", voice_id="bm_george")

    assert len(model.runs) == 1


def test_the_model_gets_padded_tokens_the_matching_style_row_and_the_speed(
    voice: KokoroVoice, model: FakeModel
) -> None:
    voice.synthesise("so on", voice_id="af_heart", speed=1.2)

    sent = model.runs[0]
    expected = [VOCAB[character] for character in "so on"]
    assert sent["tokens"].tolist() == [[0, *expected, 0]]
    assert sent["tokens"].dtype == np.int64
    # Five tokens use row four of the voice.
    assert sent["style"].shape == (1, 256)
    assert sent["style"][0, 0] == 1004
    assert sent["speed"].tolist() == [pytest.approx(1.2)]


def test_the_result_is_a_wav_with_its_length(voice: KokoroVoice) -> None:
    narration = voice.synthesise("go on", voice_id="bm_george")

    with wave.open(io.BytesIO(narration.wav), "rb") as sound:
        assert sound.getframerate() == SAMPLE_RATE == narration.sample_rate
        assert sound.getnchannels() == 1
        assert sound.getnframes() / SAMPLE_RATE == pytest.approx(narration.duration_s)
    assert narration.engine == "kokoro"


def test_fr10_word_timings_cover_every_word_and_skip_the_quiet_ends(voice: KokoroVoice) -> None:
    text = "Small steps still count"

    narration = voice.synthesise(text, voice_id="bm_george")

    assert [word.text for word in narration.words] == text.split()
    assert narration.words[0].start_s == pytest.approx(0.2, abs=0.03)
    assert narration.words[-1].end_s == pytest.approx(narration.duration_s - 0.2, abs=0.03)


def test_fr10_dictionary_phonemes_go_straight_to_the_model(model: FakeModel) -> None:
    asked: list[str] = []

    def recording(text: str, *, british: bool) -> str:
        asked.append(text)
        return text.lower()

    voice = KokoroVoice(
        Path("unused.onnx"),
        Path("unused.bin"),
        phonemise=recording,
        session=model,
        voices=voice_table(),
    )

    voice.synthesise("ask Nermin now", voice_id="bm_george", pronunciation={"nermin": "nˈɛɹmɪn"})

    assert asked == ["ask", "now"]
    expected = [VOCAB[character] for character in "ask nˈɛɹmɪn now"]
    assert model.runs[0]["tokens"].tolist() == [[0, *expected, 0]]


def test_a_british_voice_is_phonemised_as_british(model: FakeModel) -> None:
    accents: list[bool] = []

    def recording(text: str, *, british: bool) -> str:
        accents.append(british)
        return text.lower()

    voice = KokoroVoice(
        Path("unused.onnx"),
        Path("unused.bin"),
        phonemise=recording,
        session=model,
        voices=voice_table(),
    )

    voice.synthesise("go", voice_id="bm_george")
    voice.synthesise("go", voice_id="af_heart")

    assert accents == [True, False]


def test_characters_the_model_does_not_know_are_left_out(
    voice: KokoroVoice, model: FakeModel
) -> None:
    voice.synthesise("do 4 it", voice_id="bm_george")

    expected = [VOCAB[character] for character in "do it"]
    assert model.runs[0]["tokens"].tolist() == [[0, *expected, 0]]


def test_a_very_long_passage_is_split_at_sentence_ends_and_joined(
    voice: KokoroVoice, model: FakeModel
) -> None:
    sentence = "small steps still count every single day"
    text = ". ".join([sentence] * 20) + "."

    narration = voice.synthesise(text, voice_id="bm_george")

    assert len(model.runs) == 2
    for sent in model.runs:
        tokens = sent["tokens"][0].tolist()
        assert len(tokens) - 2 <= MAX_TOKENS
        # Every part ends on a full stop, never in the middle of a sentence.
        assert tokens[-2] == VOCAB["."]
    spoken = sum(sent["tokens"].shape[1] for sent in model.runs) * 0.05
    assert narration.duration_s == pytest.approx(spoken + 0.8, abs=0.01)
    assert len(narration.words) == len(text.split())


def test_an_unknown_voice_names_the_ones_that_exist(voice: KokoroVoice) -> None:
    with pytest.raises(VoiceError, match="bm_nobody") as caught:
        voice.synthesise("go", voice_id="bm_nobody")

    assert "bm_george" in str(caught.value)


def test_d5_only_english_voices_are_offered(voice: KokoroVoice) -> None:
    with pytest.raises(VoiceError, match="English"):
        voice.synthesise("go", voice_id="jf_alpha")


@pytest.mark.parametrize("speed", [0.4, 2.5])
def test_a_speed_the_model_cannot_do_is_refused(voice: KokoroVoice, speed: float) -> None:
    with pytest.raises(VoiceError, match="speed"):
        voice.synthesise("go", voice_id="bm_george", speed=speed)


def test_empty_narration_is_refused(voice: KokoroVoice) -> None:
    with pytest.raises(VoiceError, match="no narration"):
        voice.synthesise("  ", voice_id="bm_george")


def test_narration_with_nothing_speakable_is_refused(voice: KokoroVoice) -> None:
    with pytest.raises(VoiceError, match="nothing the voice can say"):
        voice.synthesise("42 %", voice_id="bm_george")


def test_a_bad_dictionary_stops_before_the_model_runs(voice: KokoroVoice, model: FakeModel) -> None:
    with pytest.raises(VoiceError, match="Nermin"):
        voice.synthesise("go", voice_id="bm_george", pronunciation={"Nermin": "n#"})

    assert model.runs == []


def test_missing_model_files_say_how_to_get_them(tmp_path: Path) -> None:
    voice = KokoroVoice(tmp_path / "kokoro.onnx", tmp_path / "voices.bin")

    with pytest.raises(VoiceError, match="make models"):
        voice.synthesise("go", voice_id="bm_george")


def test_the_token_table_matches_the_model() -> None:
    # The model file was trained with exactly these numbers (114 symbols, ids up to 177).
    assert len(VOCAB) == 114
    assert VOCAB["."] == 4
    assert VOCAB[" "] == 16
    assert max(VOCAB.values()) == 177
