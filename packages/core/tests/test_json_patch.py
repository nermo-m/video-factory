"""The small JSON Patch the revise skill's answers are applied with."""

from __future__ import annotations

from typing import Any

import pytest

from packages.core.json_patch import PatchError, apply

SPEC: dict[str, Any] = {
    "theme": "night_scrolls",
    "scenes": [
        {"id": "s01_hook", "narration": "Small steps still count.", "text": [{"content": "A"}]},
        {"id": "s02_climb", "narration": "He climbed the hill."},
    ],
    "a/b": {"c~d": 1},
}


def test_replace_changes_one_value_and_nothing_else() -> None:
    patched = apply(SPEC, [{"op": "replace", "path": "/scenes/1/narration", "value": "She did."}])

    assert patched["scenes"][1]["narration"] == "She did."
    assert patched["scenes"][0] == SPEC["scenes"][0]
    assert SPEC["scenes"][1]["narration"] == "He climbed the hill.", "the original is untouched"


def test_add_sets_a_key_inserts_into_a_list_and_appends_with_a_dash() -> None:
    patched = apply(
        SPEC,
        [
            {"op": "add", "path": "/scenes/0/title", "value": "THE HOOK"},
            {"op": "add", "path": "/scenes/0/text/0", "value": {"content": "FIRST"}},
            {"op": "add", "path": "/scenes/0/text/-", "value": {"content": "LAST"}},
        ],
    )

    assert patched["scenes"][0]["title"] == "THE HOOK"
    assert [item["content"] for item in patched["scenes"][0]["text"]] == ["FIRST", "A", "LAST"]


def test_remove_deletes_a_key_or_a_list_item() -> None:
    patched = apply(
        SPEC,
        [{"op": "remove", "path": "/scenes/0/text"}, {"op": "remove", "path": "/scenes/1"}],
    )

    assert "text" not in patched["scenes"][0]
    assert len(patched["scenes"]) == 1


def test_operations_apply_in_order() -> None:
    patched = apply(
        SPEC,
        [
            {"op": "add", "path": "/seed", "value": 1},
            {"op": "replace", "path": "/seed", "value": 2},
        ],
    )

    assert patched["seed"] == 2


def test_slashes_and_tildes_in_names_are_escaped_as_the_standard_says() -> None:
    assert apply(SPEC, [{"op": "replace", "path": "/a~1b/c~0d", "value": 2}])["a/b"]["c~d"] == 2


def test_a_value_is_copied_so_later_changes_do_not_reach_the_patch() -> None:
    value = {"content": "X"}

    patched = apply(SPEC, [{"op": "add", "path": "/scenes/0/text/-", "value": value}])
    patched["scenes"][0]["text"][-1]["content"] = "changed"

    assert value == {"content": "X"}


@pytest.mark.parametrize(
    ("operation", "words"),
    [
        ({"op": "replace", "path": "/scenes/5/narration", "value": "x"}, "no position 5"),
        ({"op": "replace", "path": "/nothing", "value": 1}, "Nothing exists"),
        ({"op": "remove", "path": "/scenes/0/nothing"}, "Nothing exists"),
        ({"op": "remove", "path": "/scenes/-"}, "not a position"),
        ({"op": "add", "path": "/scenes/9", "value": {}}, "no position 9"),
        ({"op": "add", "path": "/scenes/01", "value": {}}, "not a position"),
        ({"op": "replace", "path": "/theme/deeper", "value": 1}, "Nothing exists"),
        ({"op": "replace", "path": "scenes", "value": []}, "must start with"),
        ({"op": "replace", "path": "", "value": {}}, "whole document"),
        ({"op": "move", "path": "/theme", "from": "/seed"}, "must be one of"),
        ({"op": "replace", "path": "/theme"}, "has no value"),
        ({"path": "/theme", "value": 1}, "must be one of"),
    ],
)
def test_a_patch_that_cannot_be_applied_says_which_operation_and_why(
    operation: dict[str, Any], words: str
) -> None:
    with pytest.raises(PatchError, match=words) as raised:
        apply(SPEC, [{"op": "add", "path": "/ok", "value": 1}, operation])

    assert "Operation 2" in str(raised.value) or "must be one of" in str(raised.value)
