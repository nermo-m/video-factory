"""What a plan refers to must exist: characters, scenes and pictures (plan schema 2.1).

The schema checks the shape of a plan. These checks are about its parts pointing at each
other, which a schema cannot say.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from packages.core import schemas, specs

FIXTURES = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid"


def shots() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES / "shots.json").read_text(encoding="utf-8"))
    return loaded


def old_plan() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (FIXTURES / "all_scene_kinds.json").read_text(encoding="utf-8")
    )
    return loaded


def test_the_fixtures_refer_only_to_what_exists() -> None:
    assert specs.reference_problems(shots()) == []
    assert specs.reference_problems(old_plan()) == []


def test_a_scene_asset_that_lists_an_unknown_character_is_refused() -> None:
    spec = shots()
    spec["characters"] = []

    problems = specs.reference_problems(spec)

    assert problems == [
        "/assets/0/characters/0: the picture a_s01_hill shows the character 'keeper', "
        "and the plan has no character with that id. Scene s01_hill uses this picture."
    ]


def test_a_renamed_character_is_reported_for_every_picture_that_still_uses_the_old_id() -> None:
    spec = shots()
    spec["characters"][0]["id"] = "old_keeper"
    spec["assets"][1]["characters"] = ["keeper"]

    problems = specs.reference_problems(spec)

    assert [problem.split(":")[0] for problem in problems] == [
        "/assets/0/characters/0",
        "/assets/1/characters/0",
    ]


def test_two_characters_with_one_id_are_refused() -> None:
    spec = shots()
    spec["characters"].append(copy.deepcopy(spec["characters"][0]))

    assert specs.reference_problems(spec) == [
        "/characters/1/id: two characters have the id 'keeper'."
    ]


def test_a_change_that_names_an_unknown_scene_is_refused() -> None:
    spec = shots()
    spec["changes"][0]["scene"] = "s09_gone"

    assert specs.reference_problems(spec) == [
        "/changes/0/scene: the change list names the scene 's09_gone', "
        "which the plan does not have."
    ]


def test_a_shot_whose_picture_is_not_among_the_assets_is_refused() -> None:
    spec = shots()
    spec["assets"].pop()

    assert specs.reference_problems(spec) == [
        "/scenes/1/visual/asset_id: scene s02_lamp shows the picture 'a_s02_lamp', "
        "which the plan does not have."
    ]


def test_two_scenes_with_one_id_are_refused() -> None:
    spec = shots()
    spec["scenes"][1]["id"] = "s01_hill"

    assert "/scenes/1/id: two scenes have the id 's01_hill'." in specs.reference_problems(spec)
