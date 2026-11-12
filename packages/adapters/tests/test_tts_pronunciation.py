"""Pronunciation dictionary (design doc section 7.4, FR-10).

A channel-level dictionary maps words to phoneme strings. A word found in it is spoken
from its phonemes. Everything else goes through the normal text-to-phoneme step.
"""

from __future__ import annotations

from packages.adapters.tts.pronunciation import (
    Mark,
    Phonemes,
    Piece,
    Speak,
    check_dictionary,
    join_phonemes,
    plan_passage,
)

VOCAB = set("abdefhijklmnoprstuvwzəɛɪˈˌː ,.!?—")


def test_text_without_dictionary_words_is_spoken_as_written() -> None:
    assert plan_passage("Small steps still count", {}) == [Speak("Small steps still count")]


def test_punctuation_is_kept_as_marks_between_the_spoken_parts() -> None:
    assert plan_passage("Wait, friend. Go on!", {}) == [
        Speak("Wait"),
        Mark(","),
        Speak("friend"),
        Mark("."),
        Speak("Go on"),
        Mark("!"),
    ]


def test_fr10_a_dictionary_word_is_replaced_by_its_phonemes() -> None:
    pieces = plan_passage("Ask Nermin today", {"Nermin": "nˈɛrmin"})

    assert pieces == [Speak("Ask"), Phonemes("nˈɛrmin"), Speak("today")]


def test_fr10_the_dictionary_matches_whatever_the_case() -> None:
    assert plan_passage("NERMIN", {"nermin": "nˈɛrmin"}) == [Phonemes("nˈɛrmin")]
    assert plan_passage("nermin", {"Nermin": "nˈɛrmin"}) == [Phonemes("nˈɛrmin")]


def test_fr10_punctuation_around_a_dictionary_word_is_kept() -> None:
    pieces = plan_passage("Hello, Nermin.", {"Nermin": "nˈɛrmin"})

    assert pieces == [Speak("Hello"), Mark(","), Phonemes("nˈɛrmin"), Mark(".")]


def test_fr10_only_whole_words_are_replaced() -> None:
    dictionary = {"ana": "ˈanə"}

    assert plan_passage("A banana for Ana", dictionary) == [
        Speak("A banana for"),
        Phonemes("ˈanə"),
    ]


def test_a_decimal_point_or_an_apostrophe_does_not_split_a_word() -> None:
    assert plan_passage("It's 3.5 metres", {}) == [Speak("It's 3.5 metres")]


def test_joined_phonemes_have_single_spaces_and_marks_hug_the_word_before() -> None:
    pieces: list[Piece] = [
        Speak("Hello"),
        Mark(","),
        Phonemes("nˈɛrmin"),
        Speak("is here"),
        Mark("."),
    ]

    joined = join_phonemes(pieces, spoken=["həlˈəʊ", "ɪz hˈiə"])

    assert joined == "həlˈəʊ, nˈɛrmin ɪz hˈiə."


def test_a_good_dictionary_has_no_problems() -> None:
    assert check_dictionary({"Nermin": "nˈɛrmin", "Kokoro": "kəkˈɔːrəʊ"}, VOCAB | {"ɔ", "ʊ"}) == []


def test_phonemes_the_voice_does_not_know_are_reported_with_the_word() -> None:
    problems = check_dictionary({"Nermin": "nˈɛrmin#7"}, VOCAB)

    assert len(problems) == 1
    assert "Nermin" in problems[0]
    assert "#" in problems[0]
    assert "7" in problems[0]


def test_a_dictionary_entry_must_be_one_word_with_some_phonemes() -> None:
    problems = check_dictionary({"New York": "nˈuː", "empty": " "}, VOCAB)

    assert len(problems) == 2
    assert "New York" in problems[0]
    assert "empty" in problems[1]


def test_a_dash_between_two_words_separates_them() -> None:
    assert plan_passage("steps—small ones", {}) == [Speak("steps"), Mark("—"), Speak("small ones")]
