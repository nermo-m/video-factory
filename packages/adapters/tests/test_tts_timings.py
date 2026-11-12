"""Word timing estimate (design doc section 7.3, FR-10).

Kokoro returns audio only. Word times are estimated: each sentence's audio time is shared
between its words by character count, with extra weight after punctuation.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from packages.adapters.tts.timings import estimate_word_timings


def test_fr10_every_narration_word_gets_one_timing_as_written() -> None:
    text = "To everyone who keeps putting it off. Small steps still count."

    words = estimate_word_timings(text, 4.0)

    # The resolver counts words with str.split, so the counts must agree exactly.
    assert [word.text for word in words] == text.split()


def test_a_token_without_letters_still_gets_a_timing() -> None:
    text = "Wait — not yet."

    assert [word.text for word in estimate_word_timings(text, 2.0)] == ["Wait", "—", "not", "yet."]


def test_no_narration_gives_no_timings() -> None:
    assert estimate_word_timings("   ", 1.0) == []


def test_words_are_in_order_do_not_overlap_and_stay_inside_the_audio() -> None:
    words = estimate_word_timings("One small thing, done daily. It adds up!", 3.7)

    assert words[0].start_s >= 0
    assert words[-1].end_s <= 3.7
    for word in words:
        assert word.end_s > word.start_s
    for earlier, later in pairwise(words):
        assert later.start_s >= earlier.end_s


def test_a_longer_word_gets_proportionally_more_time() -> None:
    short, long = estimate_word_timings("go bananas", 1.0)

    assert (long.end_s - long.start_s) == pytest.approx(
        (short.end_s - short.start_s) * len("bananas") / len("go"), rel=0.01
    )


def test_plain_words_follow_each_other_without_a_gap() -> None:
    first, second = estimate_word_timings("small steps", 1.0)

    assert second.start_s == pytest.approx(first.end_s)
    assert first.start_s == 0
    assert second.end_s == pytest.approx(1.0)


def test_a_pause_follows_punctuation_and_is_longer_after_a_sentence() -> None:
    words = estimate_word_timings("wait, friend. go on", 3.0)
    after_comma = words[1].start_s - words[0].end_s
    after_sentence = words[2].start_s - words[1].end_s
    plain = words[3].start_s - words[2].end_s

    assert plain == pytest.approx(0)
    assert after_comma > 0.05
    assert after_sentence > after_comma


def test_the_silence_before_and_after_the_speech_belongs_to_no_word() -> None:
    words = estimate_word_timings("small steps", 2.0, silences=[(0.0, 0.3), (1.5, 2.0)])

    assert words[0].start_s == pytest.approx(0.3)
    assert words[-1].end_s == pytest.approx(1.5)


def test_each_sentence_fills_the_time_between_the_pauses_measured_in_the_audio() -> None:
    # Three words, a 0.4 second pause, then three long words.
    text = "It is so. Extraordinary circumstances notwithstanding."
    silences = [(0.0, 0.2), (1.0, 1.4), (4.6, 5.0)]

    words = estimate_word_timings(text, 5.0, silences=silences)

    assert words[0].start_s == pytest.approx(0.2)
    assert words[2].end_s == pytest.approx(1.0)
    assert words[3].start_s == pytest.approx(1.4)
    assert words[-1].end_s == pytest.approx(4.6)


def test_pauses_at_commas_are_used_when_the_audio_has_them() -> None:
    # Measured on the real voice: a pause at each comma, and two short gaps inside
    # phrases (after "lit" and after "checked") that are not punctuation at all.
    text = "He lit the lamp, checked the glass, and wrote."
    silences = [(0.0, 0.29), (0.53, 0.64), (1.05, 1.29), (1.46, 1.57), (2.12, 2.33), (3.0, 3.4)]

    words = estimate_word_timings(text, 3.4, silences=silences)

    assert words[3].text == "lamp,"
    assert words[3].end_s == pytest.approx(1.05)
    assert words[4].start_s == pytest.approx(1.29)
    assert words[6].text == "glass,"
    assert words[6].end_s == pytest.approx(2.12)
    assert words[7].start_s == pytest.approx(2.33)
    assert words[-1].end_s == pytest.approx(3.0)


def test_sentence_breaks_are_still_used_when_a_comma_has_no_pause_of_its_own() -> None:
    # One measured pause, two marks: the pause is the sentence break, and the comma gets
    # its share of the first sentence by weight.
    text = "Small steps, taken daily. They still count."
    silences = [(0.0, 0.2), (1.9, 2.3), (3.4, 3.8)]

    words = estimate_word_timings(text, 3.8, silences=silences)

    assert words[3].text == "daily."
    assert words[3].end_s == pytest.approx(1.9)
    assert words[4].start_s == pytest.approx(2.3)
    assert words[2].start_s - words[1].end_s > 0.05


def test_too_few_measured_pauses_fall_back_to_sharing_the_whole_passage() -> None:
    text = "One. Two. Three."
    only_the_edges = [(0.0, 0.2), (2.8, 3.0)]

    words = estimate_word_timings(text, 3.0, silences=only_the_edges)

    assert [word.text for word in words] == ["One.", "Two.", "Three."]
    assert words[0].start_s == pytest.approx(0.2)
    assert words[-1].end_s == pytest.approx(2.8)
    assert words[1].start_s > words[0].end_s


def test_a_pause_in_an_implausible_place_is_not_trusted() -> None:
    # The only long pause sits right after the first word, but the first sentence has
    # six long words. Trusting it would squeeze them into a quarter of a second.
    text = "Extraordinary circumstances notwithstanding everything continued regardless. Good."
    silences = [(0.0, 0.1), (0.35, 0.75), (5.8, 6.0)]

    words = estimate_word_timings(text, 6.0, silences=silences)

    first_sentence_end = words[5].end_s
    assert first_sentence_end > 3.0


@pytest.mark.parametrize("duration", [0.0, -1.0])
def test_audio_without_length_is_refused(duration: float) -> None:
    with pytest.raises(ValueError, match="duration"):
        estimate_word_timings("small steps", duration)
