"""The switches of one video (Director mode: nothing is forced)."""

from __future__ import annotations

from packages.core.options import NAMES, EpisodeOptions, options_of


def test_nothing_is_forced_by_default() -> None:
    assert options_of(None) == EpisodeOptions(research=False, captions=True, music=True)
    assert options_of({}) == EpisodeOptions()


def test_what_the_owner_chose_is_kept() -> None:
    chosen = options_of({"research": True, "captions": False, "music": False})

    assert chosen == EpisodeOptions(research=True, captions=False, music=False)
    assert chosen.to_json() == {"research": True, "captions": False, "music": False}


def test_a_switch_that_is_missing_has_its_default() -> None:
    assert options_of({"music": False}) == EpisodeOptions(music=False)


def test_a_value_that_is_not_true_or_false_is_ignored() -> None:
    assert options_of({"research": "yes", "captions": 0, "music": None}) == EpisodeOptions()


def test_what_is_not_a_switch_is_ignored() -> None:
    assert options_of({"theme": "night_scrolls", "research": True}) == EpisodeOptions(research=True)


def test_the_names_of_the_switches() -> None:
    assert NAMES == ("research", "captions", "music")
