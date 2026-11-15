"""The switches of one video (Director mode: nothing is forced)."""

from __future__ import annotations

from packages.core.options import (
    NAMES,
    EpisodeOptions,
    Writer,
    options_of,
    stored_options,
    writer_of,
)


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


# --- who writes the plan -------------------------------------------------------------------


def test_the_studio_chooses_who_writes_the_plan_unless_the_owner_did() -> None:
    assert writer_of(None) == Writer()
    assert writer_of({"music": False}) == Writer(tool="", model=None)
    assert Writer().text == ""


def test_the_owner_chooses_the_tool_and_the_model_that_write_the_plan() -> None:
    chosen = writer_of({"writer": "claude:claude-fable-5-2"})

    assert chosen == Writer(tool="claude", model="claude-fable-5-2")
    assert chosen.text == "claude:claude-fable-5-2"
    assert writer_of({"writer": "chatgpt"}) == Writer(tool="chatgpt", model=None)


def test_a_writer_that_is_not_one_is_ignored() -> None:
    for written in ("gemini", "claude:", "claude:--model", "chatgpt:a b", 7, None):
        assert writer_of({"writer": written}) == Writer()


def test_the_writer_is_stored_next_to_the_switches() -> None:
    stored = stored_options(EpisodeOptions(music=False), "chatgpt:gpt-5.5")

    assert stored == {
        "research": False,
        "captions": True,
        "music": False,
        "writer": "chatgpt:gpt-5.5",
    }
    assert options_of(stored) == EpisodeOptions(music=False)
    assert stored_options(EpisodeOptions(), "") == EpisodeOptions().to_json()
