"""The prompt a picture is made from (Director mode: characters are described once)."""

from __future__ import annotations

import json
from typing import Any

from packages.core import prompts, schemas

FIXTURES = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid"


def plan(name: str = "shots.json") -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return loaded


def test_the_style_and_the_characters_come_before_the_scene() -> None:
    spec = plan()
    picture = spec["assets"][0]

    assert prompts.compose(spec, picture) == (
        "Soft watercolour, muted blues, grain of rough paper.\n\n"
        "The keeper: A woman of about sixty, grey braid, yellow oilskin coat, lean and upright.\n\n"
        "A steep green hill at dusk, a narrow path, a lighthouse at the top, seen from below."
    )


def test_a_scene_without_characters_gets_none() -> None:
    spec = plan()
    picture = spec["assets"][1]

    assert prompts.compose(spec, picture) == (
        "Soft watercolour, muted blues, grain of rough paper.\n\n"
        "The lamp room of a lighthouse, a brass plate that reads KEEP THE LIGHT."
    )


def test_two_characters_are_described_in_the_order_the_picture_lists_them() -> None:
    spec = plan()
    spec["characters"].append(
        {"id": "sailor", "name": "The sailor", "description": "A boy of twelve in a blue cap."}
    )
    picture = {**spec["assets"][0], "characters": ["sailor", "keeper"]}

    composed = prompts.compose(spec, picture)

    assert composed is not None
    assert composed.index("The sailor: A boy of twelve") < composed.index("The keeper: A woman")


def test_a_plan_without_a_style_starts_with_its_characters() -> None:
    spec = plan()
    del spec["style"]

    assert str(prompts.compose(spec, spec["assets"][0])).startswith("The keeper: A woman")


def test_a_character_that_is_gone_is_left_out_not_an_error() -> None:
    """A plan is checked when it is saved. Making a picture must still not crash on one
    that slipped through."""
    spec = plan()
    spec["characters"] = []

    assert prompts.compose(spec, spec["assets"][0]) == (
        "Soft watercolour, muted blues, grain of rough paper.\n\n"
        "A steep green hill at dusk, a narrow path, a lighthouse at the top, seen from below."
    )


def test_an_old_plan_keeps_its_prompt() -> None:
    spec = plan("all_scene_kinds.json")
    picture = {"id": "a_harbour", "prompt": "A harbour at dawn.", "characters": ["keeper"]}

    assert prompts.compose({**spec, "style": "Ink."}, picture) == "A harbour at dawn."


def test_a_picture_without_a_prompt_has_none() -> None:
    spec = plan()

    assert prompts.compose(spec, {"id": "a_upload", "origin": "uploaded"}) is None


def test_who_and_what_a_picture_is_made_from_changes_with_the_character() -> None:
    spec = plan()
    before = prompts.compose(spec, spec["assets"][0])
    spec["characters"][0]["description"] = "A woman of about sixty in a red coat."

    assert prompts.compose(spec, spec["assets"][0]) != before
    assert prompts.compose(spec, spec["assets"][1]) == prompts.compose(plan(), plan()["assets"][1])
