"""JSON Schemas for the pipeline documents (design doc section 5.2).

Every fixture under schemas/fixtures validates or fails as it says it should, and each
scene kind enforces its own required fields.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from packages.core import schemas

FIXTURES = schemas.SCHEMA_DIR / "fixtures"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_files(kind: str) -> list[tuple[str, Path]]:
    return [
        (name, path)
        for name in schemas.SCHEMA_NAMES
        for path in sorted((FIXTURES / name / kind).glob("*.json"))
    ]


def fixture_id(case: tuple[str, Path]) -> str:
    return f"{case[0]}/{case[1].stem}"


VALID = fixture_files("valid")
INVALID = fixture_files("invalid")


def test_section52_the_six_schemas_exist() -> None:
    assert schemas.SCHEMA_NAMES == (
        "episode_spec",
        "resolved_spec",
        "brief",
        "claims",
        "asset_manifest",
        "package",
    )
    for name in schemas.SCHEMA_NAMES:
        assert (schemas.SCHEMA_DIR / f"{name}.schema.json").is_file()


@pytest.mark.parametrize("name", schemas.SCHEMA_NAMES)
def test_every_schema_is_a_valid_strict_2020_12_schema(name: str) -> None:
    schema = schemas.load_schema(name)

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == f"{name}.schema.json"
    assert schema["title"]
    assert schema["description"]
    # Model output drifts (risk R7): unknown properties are rejected, never ignored.
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("name", schemas.SCHEMA_NAMES)
def test_every_schema_has_valid_and_invalid_fixtures(name: str) -> None:
    assert list((FIXTURES / name / "valid").glob("*.json")), f"{name} has no valid fixture"
    assert list((FIXTURES / name / "invalid").glob("*.json")), f"{name} has no invalid fixture"


@pytest.mark.parametrize("case", VALID, ids=fixture_id)
def test_valid_fixtures_validate(case: tuple[str, Path]) -> None:
    name, path = case

    problems = schemas.validate(name, load(path))

    assert problems == [], f"{path.name} should be valid"


@pytest.mark.parametrize("case", INVALID, ids=fixture_id)
def test_invalid_fixtures_fail_where_they_say(case: tuple[str, Path]) -> None:
    name, path = case
    fixture = load(path)
    assert set(fixture) == {"why", "error_at", "document"}, "an invalid fixture explains itself"

    problems = schemas.validate(name, fixture["document"])

    assert problems, f"{path.name} should be rejected: {fixture['why']}"
    paths = [problem.path for problem in problems]
    expected = fixture["error_at"]
    assert any(found == expected or found.startswith(f"{expected}/") for found in paths), (
        f"{path.name}: expected a problem at '{expected}', found {paths}"
    )


def test_the_design_document_example_is_a_valid_authored_spec() -> None:
    example = load(FIXTURES / "episode_spec" / "valid" / "design_doc_example.json")

    assert schemas.validate("episode_spec", example) == []
    assert example["scenes"][0]["text"][0]["cue"] == {"word": 7}


# The fields each scene kind needs beyond id, kind and narration.
KIND_REQUIREMENTS = {
    "title": ["text"],
    "scroll": ["title", "visual"],
    "stat": ["stat"],
    "steps": ["steps"],
    "outro": ["text"],
}


def scene_of_kind(kind: str) -> tuple[dict[str, Any], int]:
    spec = load(FIXTURES / "episode_spec" / "valid" / "all_scene_kinds.json")
    index = next(i for i, scene in enumerate(spec["scenes"]) if scene["kind"] == kind)
    return spec, index


@pytest.mark.parametrize(
    ("kind", "field"),
    [(kind, field) for kind, fields in KIND_REQUIREMENTS.items() for field in fields],
)
def test_scene_kinds_enforce_their_own_required_fields(kind: str, field: str) -> None:
    spec, index = scene_of_kind(kind)
    assert field in spec["scenes"][index], "the fixture must start valid"
    del spec["scenes"][index][field]

    problems = schemas.validate("episode_spec", spec)

    assert any(
        problem.path == f"/scenes/{index}" and f"'{field}'" in problem.message
        for problem in problems
    ), f"a {kind} scene without {field} must be rejected, got {problems}"


@pytest.mark.parametrize("kind", sorted(KIND_REQUIREMENTS))
def test_every_scene_kind_needs_id_kind_and_narration(kind: str) -> None:
    for field in ("id", "kind", "narration"):
        spec, index = scene_of_kind(kind)
        del spec["scenes"][index][field]

        assert schemas.validate("episode_spec", spec), f"a scene without {field} must fail"


def test_optional_scene_fields_can_be_left_out() -> None:
    spec, index = scene_of_kind("scroll")
    for field in ("label", "overlays", "sound", "retention_device", "transition_out"):
        spec["scenes"][index].pop(field, None)

    assert schemas.validate("episode_spec", spec) == []


def test_all_five_scene_kinds_appear_in_the_fixture() -> None:
    spec = load(FIXTURES / "episode_spec" / "valid" / "all_scene_kinds.json")

    assert {scene["kind"] for scene in spec["scenes"]} == set(KIND_REQUIREMENTS)


def test_problems_carry_a_json_pointer_and_a_message() -> None:
    spec, index = scene_of_kind("stat")
    spec["scenes"][index]["stat"]["claim_id"] = "not a claim id"

    problems = schemas.validate("episode_spec", spec)

    assert [problem.path for problem in problems] == [f"/scenes/{index}/stat/claim_id"]
    assert "not a claim id" in problems[0].message
    assert str(problems[0]) == f"/scenes/{index}/stat/claim_id: {problems[0].message}"


def test_a_problem_at_the_top_level_has_an_empty_pointer() -> None:
    problems = schemas.validate("brief", {})

    assert {problem.path for problem in problems} == {""}
    assert str(problems[0]).startswith("(document): ")


def test_a_field_that_belongs_to_another_scene_kind_is_named_plainly() -> None:
    spec, index = scene_of_kind("title")
    spec["scenes"][index]["steps"] = [{"text": "One"}, {"text": "Two"}]

    problems = schemas.validate("episode_spec", spec)

    assert [str(problem) for problem in problems] == [
        f"/scenes/{index}/steps: 'steps' is not allowed here"
    ]


def test_formats_are_checked_not_just_documented() -> None:
    claims = load(FIXTURES / "claims" / "valid" / "with_claims.json")
    claims["claims"][0]["source_date"] = "2026-13-45"
    claims["claims"][0]["retrieved_at"] = "soon"

    paths = {problem.path for problem in schemas.validate("claims", claims)}

    assert paths == {"/claims/0/source_date", "/claims/0/retrieved_at"}


def test_validate_or_raise_lists_every_problem() -> None:
    package = load(FIXTURES / "package" / "valid" / "package.json")
    schemas.validate_or_raise("package", package)

    broken = copy.deepcopy(package)
    broken["title"] = ""
    broken["hashtags"] = ["no hash"]
    with pytest.raises(schemas.SchemaValidationError) as raised:
        schemas.validate_or_raise("package", broken)

    assert raised.value.schema == "package"
    assert {problem.path for problem in raised.value.problems} == {"/title", "/hashtags/0"}
    assert "/title" in str(raised.value)
    assert "/hashtags/0" in str(raised.value)


def test_an_unknown_schema_name_is_an_error() -> None:
    with pytest.raises(KeyError, match="storyboard"):
        schemas.validate("storyboard", {})


def test_resolved_spec_reuses_the_authored_definitions() -> None:
    resolved = schemas.load_schema("resolved_spec")

    assert resolved["properties"]["format"] == {"$ref": "episode_spec.schema.json#/$defs/format"}
    assert resolved["properties"]["claims"]["items"] == {"$ref": "claims.schema.json#/$defs/claim"}
