"""The voice adapter's twin: bundled sample audio when the model files are missing (3.3)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from packages.adapters.tts import create_tts_adapter
from packages.adapters.tts.audio import to_wav
from packages.adapters.tts.base import Narration, VoiceError
from packages.adapters.tts.kokoro import KokoroVoice
from packages.adapters.tts.samples import SampleVoice, sample_key, write_sample
from packages.adapters.tts.timings import estimate_word_timings

RATE = 24000
TEXT = "Small steps still count."


def recorded(text: str = TEXT) -> Narration:
    """A narration as the real voice would return it: quiet, speech, quiet."""
    steps = np.arange(RATE) / RATE
    speech = (0.3 * np.sin(2 * np.pi * 200 * steps)).astype(np.float32)
    quiet = np.zeros(RATE // 5, dtype=np.float32)
    return Narration(
        wav=to_wav(np.concatenate([quiet, speech, quiet]), RATE),
        sample_rate=RATE,
        duration_s=1.4,
        words=estimate_word_timings(text, 1.4, [(0.0, 0.2), (1.2, 1.4)]),
        engine="kokoro",
    )


def test_a_recorded_narration_is_returned_for_the_same_request(tmp_path: Path) -> None:
    original = recorded()
    write_sample(tmp_path, original, text=TEXT, voice_id="bm_george", speed=1.0)

    narration = SampleVoice(tmp_path).synthesise(TEXT, voice_id="bm_george", speed=1.0)

    assert narration.wav == original.wav
    assert narration.sample_rate == RATE
    assert narration.duration_s == pytest.approx(1.4)
    assert narration.engine == "sample"


def test_fr10_a_sample_gets_word_timings_from_its_audio(tmp_path: Path) -> None:
    write_sample(tmp_path, recorded(), text=TEXT, voice_id="bm_george", speed=1.0)

    narration = SampleVoice(tmp_path).synthesise(TEXT, voice_id="bm_george")

    assert [word.text for word in narration.words] == TEXT.split()
    assert narration.words[0].start_s == pytest.approx(0.2, abs=0.03)
    assert narration.words[-1].end_s == pytest.approx(1.2, abs=0.03)


def test_spacing_does_not_matter_but_voice_speed_and_words_do() -> None:
    key = sample_key(TEXT, voice_id="bm_george", speed=1.0)

    assert sample_key("  Small  steps still\ncount. ", voice_id="bm_george", speed=1.0) == key
    assert sample_key(TEXT, voice_id="af_heart", speed=1.0) != key
    assert sample_key(TEXT, voice_id="bm_george", speed=1.1) != key
    assert sample_key("Small steps count.", voice_id="bm_george", speed=1.0) != key


def test_only_dictionary_words_that_are_spoken_change_the_sample() -> None:
    key = sample_key(TEXT, voice_id="bm_george", speed=1.0)

    unrelated = {"Nermin": "nˈɛɹmɪn"}
    used = {"steps": "stˈɛps"}
    assert sample_key(TEXT, voice_id="bm_george", speed=1.0, pronunciation=unrelated) == key
    assert sample_key(TEXT, voice_id="bm_george", speed=1.0, pronunciation=used) != key


def test_narration_without_a_sample_says_how_to_get_the_real_voice(tmp_path: Path) -> None:
    write_sample(tmp_path, recorded(), text=TEXT, voice_id="bm_george", speed=1.0)

    with pytest.raises(VoiceError, match="make models") as caught:
        SampleVoice(tmp_path).synthesise("Something else entirely.", voice_id="bm_george")

    assert "no bundled sample" in str(caught.value)


def test_the_real_voice_is_used_when_both_model_files_are_there(tmp_path: Path) -> None:
    model, voices = tmp_path / "kokoro.onnx", tmp_path / "voices.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")

    adapter = create_tts_adapter(model, voices, samples_dir=tmp_path)

    assert isinstance(adapter, KokoroVoice)


@pytest.mark.parametrize("present", ["kokoro.onnx", "voices.bin", None])
def test_bundled_samples_are_used_when_a_model_file_is_missing(
    tmp_path: Path, present: str | None
) -> None:
    if present is not None:
        (tmp_path / present).write_bytes(b"x")

    adapter = create_tts_adapter(
        tmp_path / "kokoro.onnx", tmp_path / "voices.bin", samples_dir=tmp_path
    )

    assert isinstance(adapter, SampleVoice)
