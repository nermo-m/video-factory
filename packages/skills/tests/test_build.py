"""From a shot list to the plan the render engine draws (Director mode).

The model writes the shot list. Ordinary code builds the plan from it, so ids, format,
voice and seed are never the model's to get wrong.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import pytest

from packages.core import schemas, specs
from packages.render.theme import check_capabilities, load_theme
from packages.skills import build
from packages.skills.planner import SKILLS_DIR

EPISODE = uuid.UUID("7a1c2f6e-3b1d-4c55-9e0a-2f4b8c9d1e23")
EXAMPLE = SKILLS_DIR / "shotlist" / "examples" / "lighthouse_keeper.output.json"


def shotlist() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return loaded


def built(made: dict[str, Any], **options: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "episode_id": EPISODE,
        "voice_id": "bm_george",
        "voice_speed": 1.0,
        "captions": True,
        "music": True,
        "claims": [],
        **options,
    }
    return build.build_spec(made, **settings)


def one(narration: str, **fields: Any) -> dict[str, Any]:
    scene = copy.deepcopy(shotlist()["scenes"][0])
    scene.update({"id": "s1", "narration": narration, "characters": [], **fields})
    scene.pop("duration_s", None)
    scene.update(fields)
    return {**shotlist(), "characters": [], "changes": [], "scenes": [scene]}


def test_the_built_spec_fits_schema_2_1_and_the_plain_theme() -> None:
    spec = built(shotlist())

    assert schemas.validate("episode_spec", spec) == []
    assert specs.reference_problems(spec) == []
    assert check_capabilities(spec, load_theme("plain").capabilities) == []
    assert (spec["spec_version"], spec["theme"]) == ("2.1", "plain")
    assert spec["episode_id"] == str(EPISODE)
    assert (spec["format"]["width"], spec["format"]["height"]) == (1080, 1920)
    assert spec["format"]["fps"] == 30
    assert spec["voice"] == {"voice_id": "bm_george", "speed": 1.0}


def test_the_style_the_characters_and_the_change_list_are_carried_over() -> None:
    made = shotlist()

    spec = built(made)

    assert spec["style"] == made["style"]
    assert spec["characters"] == made["characters"]
    assert spec["changes"][: len(made["changes"])] == made["changes"]


def test_one_generated_picture_per_scene() -> None:
    made = shotlist()

    spec = built(made)

    assert [scene["kind"] for scene in spec["scenes"]] == ["shot"] * len(made["scenes"])
    assert [scene["visual"]["asset_id"] for scene in spec["scenes"]] == [
        f"a_{scene['id']}" for scene in made["scenes"]
    ]
    for asset, scene in zip(spec["assets"], made["scenes"], strict=True):
        assert asset == {
            "id": f"a_{scene['id']}",
            "kind": "image",
            "origin": "generated",
            "prompt": scene["image_prompt"],
            "characters": scene["characters"],
            "text_in_picture": scene["text_in_picture"],
            "contains_third_party_ip": scene["third_party"],
            "rights_status": "needs_review",
        }


def test_a_shot_carries_its_line_its_text_its_camera_and_its_motion() -> None:
    made = shotlist()
    written = made["scenes"][0]

    shot = built(made)["scenes"][0]

    assert shot["narration"] == written["narration"]
    assert shot["narration_from"] == written["narration_from"]
    assert shot["visual"] == {
        "asset_id": f"a_{written['id']}",
        "clip": written["clip"],
        "camera": written["camera"],
        "motion": written["motion_prompt"],
    }
    assert shot.get("text", []) == [
        {"content": item["content"], "style": "plain", "position": item["position"]}
        for item in written["on_screen_text"]
    ]


def test_the_switches_and_the_claims_are_the_apps_not_the_models() -> None:
    claim = {
        "id": "c_first",
        "text": "Small habits last.",
        "source_url": "https://example.org/habits",
        "source_name": "Habits (test fixture, not a real source)",
        "source_date": "2026-01-15",
        "passage": "Small habits last longer than large ones.",
        "retrieved_at": "2026-11-14T10:00:00Z",
    }

    spec = built(shotlist(), captions=False, music=False, claims=[claim])

    assert (spec["captions"], spec["music"]) == (False, False)
    assert spec["claims"] == [claim]
    assert schemas.validate("episode_spec", spec) == []


def test_the_same_episode_gets_the_same_seed() -> None:
    assert built(shotlist())["seed"] == built(shotlist())["seed"] == EPISODE.int % 2**32
    assert built(shotlist(), episode_id=uuid.uuid4())["seed"] != built(shotlist())["seed"]


def test_a_scene_shorter_than_its_line_is_lengthened_and_listed() -> None:
    line = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    spec = built(one(line, duration_s=2))

    assert "duration_s" not in spec["scenes"][0]
    assert spec["changes"] == [
        {
            "scene": "s1",
            "kind": "changed",
            "what": "The scene lasts as long as its line.",
            "why": "The line takes about 6.8 seconds to speak and the scene was given 2.",
        }
    ]


def test_a_scene_given_more_seconds_than_its_line_takes_keeps_them() -> None:
    spec = built(one("one two three", duration_s=9))

    assert spec["scenes"][0]["duration_s"] == 9
    assert spec["changes"] == []


def test_a_silent_shot_without_seconds_takes_three() -> None:
    spec = built(one(""))

    assert spec["scenes"][0]["duration_s"] == 3
    assert "narration_from" not in spec["scenes"][0]


def test_a_silent_shot_list_builds() -> None:
    made = shotlist()
    for index, scene in enumerate(made["scenes"]):
        scene.update(narration="", duration_s=4 + index)
    spec = built(made)

    assert schemas.validate("episode_spec", spec) == []
    assert spec["format"]["target_duration_s"] == sum(4 + i for i in range(len(made["scenes"])))


def test_the_length_is_what_the_scenes_need() -> None:
    line = "one two three four five six seven eight nine ten eleven twelve"
    made = one(line)
    made["scenes"] = [{**made["scenes"][0], "id": f"s{n}"} for n in range(4)]

    spec = built(made)

    assert spec["format"]["target_duration_s"] == round(4 * (12 / 2.3 + 0.7))
    assert spec["changes"] == []


def test_a_short_video_is_at_least_fifteen_seconds_on_paper() -> None:
    assert built(one("one two three"))["format"]["target_duration_s"] == 15


def test_a_stated_length_shorter_than_the_lines_is_listed() -> None:
    line = "one two three four five six seven eight nine ten eleven twelve"
    made = one(line)
    made["scenes"] = [{**made["scenes"][0], "id": f"s{n}"} for n in range(6)]
    made["target_duration_s"] = 20

    spec = built(made)

    assert spec["format"]["target_duration_s"] == 36
    assert spec["changes"] == [
        {
            "kind": "changed",
            "what": "The video is about 36 seconds long, not 20.",
            "why": "The lines take that long to speak, and a line is never cut.",
        }
    ]


def test_a_stated_length_the_lines_fit_into_changes_nothing() -> None:
    made = one("one two three four five six")
    made["target_duration_s"] = 30

    spec = built(made)

    assert spec["changes"] == []
    assert spec["format"]["target_duration_s"] == 15


def test_more_than_180_seconds_raises_too_long() -> None:
    line = " ".join(["word"] * 60)
    made = one(line)
    made["scenes"] = [{**made["scenes"][0], "id": f"s{n}"} for n in range(8)]

    with pytest.raises(build.TooLongError) as raised:
        built(made)

    assert raised.value.needed_s == round(8 * (60 / 2.3 + 0.7))
    assert "214" in str(raised.value)


def test_exactly_at_the_limit_is_built() -> None:
    made = shotlist()
    for scene in made["scenes"]:
        scene.update(narration="", duration_s=180 / len(made["scenes"]))

    assert built(made)["format"]["target_duration_s"] == 180


def test_a_scene_a_fraction_of_a_second_short_says_so_in_tenths() -> None:
    """Seen in the first live plan: "takes about 2 seconds and the scene was given 2".
    Rounded to whole seconds the two numbers looked the same."""
    spec = built(one("one two three four", duration_s=2))

    assert spec["changes"][0]["why"] == (
        "The line takes about 2.4 seconds to speak and the scene was given 2."
    )


def test_fr07_every_shot_moves_when_the_owner_wants_the_pictures_animated() -> None:
    spec = built(shotlist(), animate=True)

    assert [scene["visual"]["clip"] for scene in spec["scenes"]] == [True] * len(spec["scenes"])


def test_fr07_no_shot_moves_when_the_owner_switched_that_off() -> None:
    spec = built(shotlist(), animate=False)

    assert not any(scene["visual"]["clip"] for scene in spec["scenes"])


def test_without_a_choice_each_shot_moves_as_the_shot_list_says() -> None:
    listed = shotlist()
    spec = built(listed)

    assert [scene["visual"]["clip"] for scene in spec["scenes"]] == [
        scene["clip"] for scene in listed["scenes"]
    ]
