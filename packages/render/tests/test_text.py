"""Caption grouping and text fitting (RN-06)."""

from __future__ import annotations

from typing import Any

import pytest

from packages.render import text
from packages.render.theme import load_theme


def words(sentence: str, start: float = 0.0, each: float = 0.5) -> list[dict[str, Any]]:
    return [
        {"text": word, "start_s": start + i * each, "end_s": start + (i + 1) * each}
        for i, word in enumerate(sentence.split())
    ]


def grouped(sentence: str) -> list[str]:
    spoken = words(sentence)
    return [" ".join(spoken[i]["text"] for i in group) for group in text.group_captions(spoken)]


def test_rn06_a_group_has_at_most_three_words() -> None:
    assert grouped("a b c d e f g") == ["a b c", "d e f", "g"]


def test_rn06_a_group_has_at_most_fourteen_characters() -> None:
    # "climbed the" is 11 characters, adding "same" would make 16.
    assert grouped("The keeper climbed the same hill") == ["The keeper", "climbed the", "same hill"]
    for group in grouped("The keeper climbed the same hill every morning nobody asked him to"):
        assert len(group) <= text.MAX_GROUP_CHARS
        assert len(group.split()) <= text.MAX_GROUP_WORDS


def test_rn06_a_long_word_stands_alone_and_is_never_split() -> None:
    assert grouped("an extraordinarily long word") == ["an", "extraordinarily", "long word"]


def test_rn06_a_group_ends_with_its_sentence() -> None:
    assert grouped("Nobody asked. He went.") == ["Nobody asked.", "He went."]
    assert grouped("Why? No one knew!") == ["Why?", "No one knew!"]


def test_rn06_no_words_no_groups() -> None:
    assert text.group_captions([]) == []


def test_rn06_the_current_word_is_the_one_being_spoken() -> None:
    spoken = words("The keeper climbed the same hill", start=10.0)
    groups = text.group_captions(spoken)

    assert text.active_caption(groups, spoken, 9.9) is None
    assert text.active_caption(groups, spoken, 10.0) == ([0, 1], 0)
    assert text.active_caption(groups, spoken, 10.74) == ([0, 1], 1)
    assert text.active_caption(groups, spoken, 11.2) == ([2, 3], 2)
    assert text.active_caption(groups, spoken, 12.9) == ([4, 5], 5)


def test_rn06_a_caption_stays_briefly_after_its_last_word() -> None:
    spoken = words("One two", start=1.0)
    groups = text.group_captions(spoken)

    # The words end at 2.0. The group lingers for a moment, then clears.
    assert text.active_caption(groups, spoken, 2.2) == ([0, 1], 1)
    assert text.active_caption(groups, spoken, 2.0 + text.CAPTION_LINGER_S + 0.01) is None


def test_rn06_a_pause_inside_a_group_keeps_the_last_spoken_word_lit() -> None:
    spoken = [
        {"text": "One", "start_s": 0.0, "end_s": 0.4},
        {"text": "two", "start_s": 1.0, "end_s": 1.4},
    ]
    groups = text.group_captions(spoken)

    assert text.active_caption(groups, spoken, 0.7) == ([0, 1], 0)


@pytest.mark.parametrize("role", ["display", "body", "hand"])
def test_rn06_text_shrinks_until_it_fits_the_width(role: str) -> None:
    font_path = load_theme("night_scrolls").fonts[role]

    short = text.fit_font(font_path, "SMALL", max_width=800, size=150, min_size=40)
    long = text.fit_font(
        font_path, "EXTRAORDINARILY LONG LINE", max_width=800, size=150, min_size=40
    )

    assert short.size == 150
    assert long.size < 150
    assert long.getlength("EXTRAORDINARILY LONG LINE") <= 800
    assert short.getlength("SMALL") <= 800


def test_text_never_shrinks_below_the_minimum_size() -> None:
    font_path = load_theme("night_scrolls").fonts["display"]

    font = text.fit_font(font_path, "X" * 200, max_width=300, size=150, min_size=40)

    assert font.size == 40


def test_the_body_font_can_be_made_bold() -> None:
    font_path = load_theme("night_scrolls").fonts["body"]

    regular = text.load_font(font_path, 80)
    bold = text.load_font(font_path, 80, weight=800)

    assert bold.getlength("Caption") > regular.getlength("Caption")
