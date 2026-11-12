"""The rules of the skills direct, assets, package and revise (design doc section 6)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from packages.core import schemas
from packages.core.queue import InvalidOutputError
from packages.skills import rules
from packages.skills.planner import SKILLS_DIR, load_skill, run_skill
from packages.skills.tests.test_planner import FakeLLM, example

ROOT = Path(__file__).resolve().parents[3]
SPEC = example("direct", "output")
DIRECT_INPUT = example("direct", "input")
ASSETS_INPUT = example("assets", "input")
MANIFEST = example("assets", "output")
REVISE_INPUT = example("revise", "input")


def changed(document: dict[str, Any], change: Any) -> dict[str, Any]:
    copied = copy.deepcopy(document)
    change(copied)
    return copied


# --- Shared schemas as one document ---------------------------------------------------------


@pytest.mark.parametrize("name", schemas.SCHEMA_NAMES)
def test_a_bundled_schema_points_nowhere_else_and_is_a_valid_schema(name: str) -> None:
    bundled = schemas.bundled_schema(name)

    Draft202012Validator.check_schema(bundled)
    assert ".schema.json#" not in json.dumps(bundled)


def test_a_bundled_schema_accepts_and_refuses_what_the_shared_one_does() -> None:
    validator = Draft202012Validator(
        schemas.bundled_schema("episode_spec"), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    wrong = changed(SPEC, lambda spec: spec["scenes"][1].update(kind="nonsense"))

    assert list(validator.iter_errors(SPEC)) == []
    assert list(validator.iter_errors(wrong)) != []
    assert schemas.validate("episode_spec", wrong) != []


def test_changing_a_bundled_schema_does_not_change_the_next_one() -> None:
    schemas.bundled_schema("brief")["properties"].clear()

    assert schemas.bundled_schema("brief")["properties"] != {}


# --- direct ---------------------------------------------------------------------------------


def direct(*answers: Any, repair: Any = None) -> Any:
    return run_skill(
        FakeLLM(*answers),
        load_skill("direct"),
        DIRECT_INPUT,
        check=rules.spec_follows_the_plan,
        repair=repair,
    )


def test_the_sample_spec_follows_its_script_and_theme() -> None:
    assert direct(SPEC).output == SPEC


def test_fr03_a_spec_using_an_undeclared_overlay_fails_validation() -> None:
    def add_hologram(spec: dict[str, Any]) -> None:
        spec["scenes"][1]["overlays"][0]["type"] = "hologram"

    wrong = changed(SPEC, add_hologram)
    llm = FakeLLM(wrong, wrong)

    with pytest.raises(InvalidOutputError):
        run_skill(llm, load_skill("direct"), DIRECT_INPUT, check=rules.spec_follows_the_plan)

    assert "overlays" in llm.requests[1].prompt


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (lambda spec: spec["scenes"][1]["sound"][0].update(cue_id="thunder"), "thunder"),
        (lambda spec: spec["scenes"][0].update(transition_out="wipe"), "wipe"),
        (lambda spec: spec["scenes"][1]["overlays"][1].update(name="dragon"), "dragon"),
        (lambda spec: spec["scenes"][1]["overlays"][1].update(action="explode"), "explode"),
    ],
)
def test_a_spec_may_only_use_what_the_theme_declares(change: Any, words: str) -> None:
    wrong = changed(SPEC, change)
    llm = FakeLLM(wrong, SPEC)

    assert direct_with(llm).output == SPEC
    assert words in llm.requests[1].prompt.split("was not accepted")[1]


def direct_with(llm: FakeLLM) -> Any:
    return run_skill(llm, load_skill("direct"), DIRECT_INPUT, check=rules.spec_follows_the_plan)


@pytest.mark.parametrize(
    "change",
    [
        lambda spec: spec["scenes"][2].update(narration="He cleaned the glass. A lot."),
        lambda spec: spec["scenes"].pop(3),
        lambda spec: spec["scenes"].reverse(),
        lambda spec: spec["scenes"][1].update(id="s02_hill"),
    ],
)
def test_the_director_may_not_rewrite_reorder_or_drop_the_scripts_scenes(change: Any) -> None:
    llm = FakeLLM(changed(SPEC, change), SPEC)

    direct_with(llm)

    assert "word for word" in llm.requests[1].prompt


def test_a_picture_a_scene_shows_must_be_declared() -> None:
    llm = FakeLLM(changed(SPEC, lambda spec: spec["assets"].pop(0)), SPEC)

    direct_with(llm)

    assert "which `assets` does not list" in llm.requests[1].prompt


def test_a_library_picture_must_be_in_the_library() -> None:
    def invent(spec: dict[str, Any]) -> None:
        spec["assets"][0]["id"] = "a_made_up"
        spec["scenes"][1]["visual"]["asset_id"] = "a_made_up"

    llm = FakeLLM(changed(SPEC, invent), SPEC)

    direct_with(llm)

    assert "a_made_up is not in the library" in llm.requests[1].prompt


def test_what_the_app_knows_is_written_into_the_spec_whatever_the_model_wrote() -> None:
    fixed = {
        "episode_id": "ep_real_one",
        "seed": 99,
        "voice": {"voice_id": "bm_george", "speed": 1.0},
    }
    answer = changed(SPEC, lambda spec: spec.update(episode_id="placeholder", seed=1))

    result = direct(answer, repair=rules.complete_spec(fixed))

    assert (result.output["episode_id"], result.output["seed"]) == ("ep_real_one", 99)
    assert result.output["scenes"] == SPEC["scenes"]


# --- assets ---------------------------------------------------------------------------------


def assets(*answers: Any, inputs: dict[str, Any] | None = None) -> Any:
    return run_skill(
        FakeLLM(*answers),
        load_skill("assets"),
        inputs or ASSETS_INPUT,
        check=rules.manifest_covers_the_spec,
    )


def test_the_sample_manifest_covers_the_sample_spec() -> None:
    assert assets(MANIFEST).output == MANIFEST


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (lambda manifest: manifest["assets"].pop(0), "does not list it"),
        (lambda manifest: manifest["assets"][0].update(used_in=["s07_outro"]), "`used_in` says"),
        (lambda manifest: manifest["assets"][0].update(becomes_clip=True), "`becomes_clip`"),
        (lambda manifest: manifest["assets"][0].update(library_key="a_unknown"), "does not have"),
    ],
)
def test_a_manifest_that_does_not_match_the_spec_is_sent_back(change: Any, words: str) -> None:
    llm = FakeLLM(changed(MANIFEST, change), MANIFEST)

    result = run_skill(
        llm, load_skill("assets"), ASSETS_INPUT, check=rules.manifest_covers_the_spec
    )

    assert result.output == MANIFEST
    assert words in llm.requests[1].prompt


def generated(prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The sample with its first picture to be generated: the input and a manifest."""

    def spec_change(inputs: dict[str, Any]) -> None:
        inputs["spec"]["assets"][0].update(origin="generated", rights_status="needs_review")
        inputs["library"].pop(0)

    def manifest_change(manifest: dict[str, Any]) -> None:
        entry = manifest["assets"][0]
        entry.update(origin="generated", prompt=prompt, rights_status="needs_review")
        del entry["library_key"]

    return changed(ASSETS_INPUT, spec_change), changed(MANIFEST, manifest_change)


def test_fr01_a_generated_pictures_prompt_carries_the_channel_style_block() -> None:
    style = ASSETS_INPUT["style_block"]
    inputs, good = generated(f"A keeper climbs a hill at dawn. {style}")
    _, bare = generated("A keeper climbs a hill at dawn.")
    llm = FakeLLM(bare, good)

    result = run_skill(llm, load_skill("assets"), inputs, check=rules.manifest_covers_the_spec)

    assert result.output == good
    assert "channel style block" in llm.requests[1].prompt


def test_a_channel_without_a_style_block_asks_nothing_of_the_prompt() -> None:
    inputs, bare = generated("A keeper climbs a hill at dawn.")
    inputs["style_block"] = ""

    assert assets(bare, inputs=inputs).output == bare


# --- package --------------------------------------------------------------------------------


def test_the_sample_package_fits_its_video() -> None:
    package = example("package", "output")
    result = run_skill(
        FakeLLM(package),
        load_skill("package"),
        example("package", "input"),
        check=rules.package_fits_the_video,
    )

    assert result.output == package
    assert len(package["title"]) <= 100


def test_a_cover_frame_after_the_end_of_the_video_is_sent_back() -> None:
    package = example("package", "output")
    llm = FakeLLM({**package, "cover_frame_s": 300}, package)

    run_skill(
        llm, load_skill("package"), example("package", "input"), check=rules.package_fits_the_video
    )

    assert "45 seconds long" in llm.requests[1].prompt


# --- revise ---------------------------------------------------------------------------------


def revise(*answers: Any) -> Any:
    return run_skill(
        FakeLLM(*answers),
        load_skill("revise"),
        REVISE_INPUT,
        check=rules.patch_leaves_a_valid_spec,
    )


def patch(*operations: dict[str, Any]) -> dict[str, Any]:
    return {"summary": "A change.", "patch": list(operations)}


GOOD = example("revise", "output")


def test_fr03_the_sample_revision_is_a_minimal_patch_that_leaves_a_valid_spec() -> None:
    result = revise(GOOD)

    assert result.output == GOOD
    assert len(result.output["patch"]) == 1


@pytest.mark.parametrize(
    ("operations", "words"),
    [
        ([{"op": "replace", "path": "/scenes/40/narration", "value": "x"}], "no position 40"),
        ([{"op": "remove", "path": "/scenes/0/narration"}], "not valid"),
        ([{"op": "replace", "path": "/scenes/0/transition_out", "value": "wipe"}], "theme has no"),
        ([{"op": "replace", "path": "/episode_id", "value": "ep_other"}], "may not change"),
        ([{"op": "replace", "path": "/theme", "value": "night_scrolls_2"}], "may not change"),
        ([{"op": "replace", "path": "/seed", "value": n} for n in range(21)], "at most 20"),
    ],
)
def test_fr03_a_patch_that_breaks_the_spec_is_sent_back(
    operations: list[dict[str, Any]], words: str
) -> None:
    llm = FakeLLM(patch(*operations), GOOD)

    result = run_skill(
        llm, load_skill("revise"), REVISE_INPUT, check=rules.patch_leaves_a_valid_spec
    )

    assert result.output == GOOD
    assert words in llm.requests[1].prompt


def test_a_revision_that_stays_wrong_fails() -> None:
    wrong = patch({"op": "remove", "path": "/scenes/0/narration"})

    with pytest.raises(InvalidOutputError):
        revise(wrong, wrong)


def test_an_empty_patch_is_not_an_answer() -> None:
    with pytest.raises(InvalidOutputError):
        revise(patch(), patch())


# --- Recordings ------------------------------------------------------------------------------


def test_the_recorded_direction_is_the_sample_episode() -> None:
    sample = json.loads(
        (ROOT / "samples" / "lighthouse_keeper" / "episode_spec.json").read_text(encoding="utf-8")
    )
    recorded = json.loads(
        (ROOT / "samples" / "recordings" / "direct.json").read_text(encoding="utf-8")
    )

    assert recorded["output"] == sample
    assert (SKILLS_DIR / "direct" / "SKILL.md").is_file()
