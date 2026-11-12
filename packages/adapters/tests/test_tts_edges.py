"""Edge cases of the voice adapters: unusual narration, damaged files, extreme lengths."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np
import pytest

from packages.adapters.tts.audio import find_silences, read_wav
from packages.adapters.tts.base import VoiceError
from packages.adapters.tts.kokoro import split_batches
from packages.adapters.tts.pronunciation import Mark, Speak, join_phonemes, plan_passage
from packages.adapters.tts.samples import SampleVoice, sample_key
from packages.adapters.tts.timings import estimate_word_timings


def test_a_passage_that_fits_is_one_batch() -> None:
    assert split_batches("small steps. still count.", 510) == ["small steps. still count."]


def test_sentences_are_packed_together_up_to_the_limit() -> None:
    batches = split_batches("aaaa bbbb. cccc dddd. eeee ffff.", 22)

    assert batches == ["aaaa bbbb. cccc dddd.", "eeee ffff."]


def test_a_sentence_longer_than_the_limit_is_cut_at_spaces() -> None:
    batches = split_batches("aaaa bbbb cccc dddd eeee.", 10)

    assert batches == ["aaaa bbbb", "cccc dddd", "eeee."]
    assert all(len(batch) <= 10 for batch in batches)


def test_a_single_word_longer_than_the_limit_is_cut_anyway() -> None:
    batches = split_batches("aaaaaaaaaaaa bb.", 5)

    assert batches == ["aaaaa", "aaaaa", "aa", "bb."]


def test_an_opening_quote_stays_with_the_word_after_it() -> None:
    pieces = plan_passage('He said "go now".', {})

    assert pieces == [Speak("He said"), Mark('"', opens=True), Speak("go now"), Mark('".')]
    assert join_phonemes(pieces, spoken=["hi sed", "go now"]) == 'hi sed "go now".'


def test_a_damaged_bundled_sample_is_reported_by_name(tmp_path: Path) -> None:
    key = sample_key("Small steps.", voice_id="bm_george", speed=1.0)
    (tmp_path / f"{key}.wav").write_bytes(b"not audio")

    with pytest.raises(VoiceError, match=f"{key}.wav"):
        SampleVoice(tmp_path).synthesise("Small steps.", voice_id="bm_george")


def test_a_stereo_wav_is_refused() -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sound:
        sound.setnchannels(2)
        sound.setsampwidth(2)
        sound.setframerate(24000)
        sound.writeframes(b"\x00\x00" * 200)

    with pytest.raises(ValueError, match="mono"):
        read_wav(buffer.getvalue())


def test_audio_shorter_than_one_measuring_window_has_no_silences() -> None:
    assert find_silences(np.zeros(100, dtype=np.float32), 24000) == []


def test_audio_measured_as_silent_throughout_still_gets_timings() -> None:
    words = estimate_word_timings("small steps", 2.0, silences=[(0.0, 2.0)])

    assert [word.text for word in words] == ["small", "steps"]
    assert words[0].start_s == 0
    assert words[-1].end_s == pytest.approx(2.0)


def test_a_quote_mark_standing_alone_is_a_word_without_a_pause() -> None:
    words = estimate_word_timings('one " two', 3.0)

    assert [word.text for word in words] == ["one", '"', "two"]
    assert words[2].start_s == pytest.approx(words[1].end_s)
