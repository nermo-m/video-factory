"""An episode's pictures as stored assets, on a real Postgres (FR-05, FR-06, FR-08)."""

from __future__ import annotations

import copy
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from packages.adapters.storage import LocalStorage
from packages.core import assets, queue
from packages.core.db import models
from packages.core.enums import AssetOrigin, JobTag, RightsStatus

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
BUNDLED = ["a_hill_dawn", "a_lamp_room", "a_lighthouse_beam", "a_storm_sea"]


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "data")


@pytest.fixture(scope="module")
def sample() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (ROOT / "samples" / "lighthouse_keeper" / "episode_spec.json").read_text(encoding="utf-8")
    )
    return loaded


def generated(asset_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": asset_id,
        "kind": "image",
        "origin": "generated",
        "prompt": f"Prompt in the spec for {asset_id}.",
        "contains_third_party_ip": False,
        "rights_status": "cleared",
        **fields,
    }


def own_spec(sample: dict[str, Any]) -> dict[str, Any]:
    """The sample with two of its pictures replaced: one to generate, one to upload."""
    spec = copy.deepcopy(sample)
    spec["assets"] = [
        asset for asset in spec["assets"] if asset["id"] in {"a_hill_dawn", "a_lamp_room"}
    ]
    spec["assets"].append(generated("a_harbour"))
    spec["assets"].append({**generated("a_my_photo"), "origin": "uploaded"})
    del spec["assets"][-1]["prompt"]
    for scene in spec["scenes"]:
        if scene["id"] == "s04_storm":
            scene["visual"] = {"asset_id": "a_harbour", "clip": True}
        if scene["id"] == "s05_light":
            scene["visual"] = {"asset_id": "a_my_photo"}
    return spec


def episode(sessions: sessionmaker[Session], channel_id: uuid.UUID | None = None) -> models.Episode:
    with sessions.begin() as session:
        if channel_id is None:
            channel = models.Channel(
                name="Small Steps", voice_id="bm_george", theme="night_scrolls"
            )
            session.add(channel)
            session.flush()
            channel_id = channel.id
        made = models.Episode(channel_id=channel_id, idea="A keeper who climbs a hill.")
        session.add(made)
        session.flush()
        return made


def prepared(
    sessions: sessionmaker[Session], storage: LocalStorage, spec: dict[str, Any]
) -> models.Episode:
    made = episode(sessions)
    with sessions.begin() as session:
        assets.ensure_library(session, storage, made.channel_id)
        assets.sync(session, made, spec)
    return made


def by_id(pictures: list[assets.Picture]) -> dict[str, assets.Picture]:
    return {picture.id: picture for picture in pictures}


# --- the library ---------------------------------------------------------------------------


def test_the_bundled_pictures_become_the_channels_first_library_assets(
    sessions: sessionmaker[Session], storage: LocalStorage, tmp_path: Path
) -> None:
    made = episode(sessions)

    with sessions.begin() as session:
        assets.ensure_library(session, storage, made.channel_id)
        assets.ensure_library(session, storage, made.channel_id)

    with sessions() as session:
        library = session.scalars(select(models.Asset).order_by(models.Asset.key)).all()
        versions = session.scalars(select(models.AssetVersion)).all()
    assert [asset.key for asset in library] == BUNDLED
    assert all(asset.episode_id is None for asset in library)
    assert {asset.origin for asset in library} == {AssetOrigin.LIBRARY}
    assert {asset.rights_status for asset in library} == {RightsStatus.CLEARED}
    assert len(versions) == 4
    assert all(version.is_active for version in versions)
    for key in BUNDLED:
        assert (tmp_path / "data" / "library" / key / "v1.png").read_bytes()[:4] == b"\x89PNG"


# --- FR-05 ---------------------------------------------------------------------------------


def test_fr05_the_sample_episode_is_resolved_from_the_library_alone(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    made = prepared(sessions, storage, sample)

    with sessions() as session:
        pictures = assets.resolve(session, made, sample)
        stored, unresolved = assets.files(pictures)

    assert unresolved == []
    assert {key: file.file for key, file in stored.items()} == {
        key: f"library/{key}/v1.png" for key in BUNDLED
    }
    assert stored["a_hill_dawn"].licence == "MIT"
    assert by_id(pictures)["a_hill_dawn"].used_in == ("s02_climb",)
    with sessions() as session:
        own = session.scalars(select(models.Asset).where(models.Asset.episode_id == made.id)).all()
    assert own == [], "a library picture needs no row of the episode's own"


def test_fr05_a_generated_and_an_uploaded_picture_get_rows_and_stay_unresolved_without_a_file(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    spec = own_spec(sample)
    made = prepared(sessions, storage, spec)

    with sessions() as session:
        pictures = by_id(assets.resolve(session, made, spec))
        stored, unresolved = assets.files(list(pictures.values()))

    assert sorted(stored) == ["a_hill_dawn", "a_lamp_room"]
    assert [picture.id for picture in unresolved] == ["a_harbour", "a_my_photo"]
    harbour = pictures["a_harbour"]
    assert harbour.asset is not None
    assert harbour.asset.key == f"{made.id}:a_harbour"
    assert harbour.asset.episode_id == made.id
    assert (harbour.origin, harbour.becomes_clip, harbour.used_in) == (
        "generated",
        True,
        ("s04_storm",),
    )
    assert harbour.prompt == "Prompt in the spec for a_harbour."
    said = assets.unresolved_text(unresolved)
    assert "a_harbour has not been generated yet" in said
    assert "a_my_photo waits for your upload" in said


def test_the_manifest_has_the_last_word_on_where_a_picture_comes_from(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    spec = own_spec(sample)
    made = episode(sessions)
    manifest = {
        "a_harbour": {
            "id": "a_harbour",
            "origin": "library",
            "library_key": "a_storm_sea",
            "licence": "MIT",
        },
        "a_my_photo": {"id": "a_my_photo", "origin": "generated", "prompt": "From the manifest."},
    }
    with sessions.begin() as session:
        assets.ensure_library(session, storage, made.channel_id)
        added = assets.sync(session, made, spec, manifest)
        pictures = by_id(assets.resolve(session, made, spec, manifest))

    assert [asset.key for asset in added] == [f"{made.id}:a_my_photo"]
    assert pictures["a_harbour"].file == "library/a_storm_sea/v1.png"
    assert pictures["a_my_photo"].prompt == "From the manifest."
    assert pictures["a_my_photo"].origin == "generated"


def test_the_newest_manifest_of_the_episode_is_read_from_its_planning_job(
    sessions: sessionmaker[Session], sample: dict[str, Any]
) -> None:
    made = episode(sessions)
    for prompt in ("First.", "Second."):
        with sessions.begin() as session:
            queue.enqueue(session, job_type="plan.assets", tag=JobTag.CPU, episode_id=made.id)
        with sessions.begin() as session:
            claim = queue.claim_next(session, JobTag.CPU)
            assert claim is not None
            document = {"episode_id": "x", "assets": [generated("a_harbour", prompt=prompt)]}
            queue.complete(session, claim, {"document": document})

    with sessions() as session:
        manifest = assets.manifest_of(session, made.id)
        nothing = assets.manifest_of(session, uuid.uuid4())

    assert manifest["a_harbour"]["prompt"] == "Second."
    assert nothing == {}


def test_syncing_again_adds_nothing_and_a_picture_that_left_the_spec_keeps_its_row(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    spec = own_spec(sample)
    made = prepared(sessions, storage, spec)
    smaller = copy.deepcopy(spec)
    smaller["assets"] = [asset for asset in smaller["assets"] if asset["id"] != "a_harbour"]
    for scene in smaller["scenes"]:
        if scene.get("visual", {}).get("asset_id") == "a_harbour":
            scene["visual"] = {"asset_id": "a_hill_dawn"}

    with sessions.begin() as session:
        again = assets.sync(session, made, spec)
        after_edit = assets.sync(session, made, smaller)
        rows = session.scalars(
            select(models.Asset.key).where(models.Asset.episode_id == made.id)
        ).all()

    assert again == []
    assert after_edit == []
    assert sorted(rows) == [f"{made.id}:a_harbour", f"{made.id}:a_my_photo"]


def test_two_episodes_of_one_channel_may_name_a_picture_the_same(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    spec = own_spec(sample)
    first = prepared(sessions, storage, spec)
    second = episode(sessions, first.channel_id)

    with sessions.begin() as session:
        assets.sync(session, second, spec)
        harbour = by_id(assets.resolve(session, first, spec))["a_harbour"].asset
        assert harbour is not None
        assets.add_version(session, harbour, file_path="jobs/gen.image/aa/one/a_harbour.png")
        of_first = by_id(assets.resolve(session, first, spec))["a_harbour"]
        of_second = by_id(assets.resolve(session, second, spec))["a_harbour"]

    assert of_first.file == "jobs/gen.image/aa/one/a_harbour.png"
    assert of_second.file is None
    assert of_first.asset is not None
    assert of_second.asset is not None
    assert of_first.asset.id != of_second.asset.id


# --- FR-06 ---------------------------------------------------------------------------------


def test_fr06_a_generated_picture_keeps_every_version_with_prompt_model_seed_and_cost(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    spec = own_spec(sample)
    made = prepared(sessions, storage, spec)

    with sessions.begin() as session:
        harbour = by_id(assets.resolve(session, made, spec))["a_harbour"].asset
        assert harbour is not None
        first = assets.add_version(
            session,
            harbour,
            file_path="jobs/gen.image/aa/one/a_harbour.png",
            prompt="A harbour at first light.",
            model="codex image tool",
            seed=7,
            width=1122,
            height=1402,
        )
    # A second version is stored by a later job, so in a later transaction.
    with sessions.begin() as session:
        second = assets.add_version(
            session,
            harbour,
            file_path="jobs/gen.image/bb/two/a_harbour.png",
            prompt="A harbour at dusk.",
            model="gpt-image",
            cost_usd=Decimal("0.04"),
        )
        kept = assets.versions(session, harbour)
        now = by_id(assets.resolve(session, made, spec))["a_harbour"]

    assert [version.id for version in kept] == [first.id, second.id]
    assert [version.is_active for version in kept] == [False, True]
    assert (kept[0].prompt, kept[0].model, kept[0].seed) == (
        "A harbour at first light.",
        "codex image tool",
        7,
    )
    assert (kept[0].width, kept[0].height) == (1122, 1402)
    assert kept[1].cost_usd == Decimal("0.04")
    assert now.file == "jobs/gen.image/bb/two/a_harbour.png"


def test_fr06_an_earlier_version_can_be_made_the_active_one_again(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    spec = own_spec(sample)
    made = prepared(sessions, storage, spec)

    with sessions.begin() as session:
        harbour = by_id(assets.resolve(session, made, spec))["a_harbour"].asset
        assert harbour is not None
        first = assets.add_version(session, harbour, file_path="one.png")
    with sessions.begin() as session:
        assets.add_version(session, harbour, file_path="two.png")
        assets.activate(session, first)
        now = by_id(assets.resolve(session, made, spec))["a_harbour"]
        active = [
            version.file_path for version in assets.versions(session, harbour) if version.is_active
        ]

    assert now.file == "one.png"
    assert active == ["one.png"]


# --- FR-08 ---------------------------------------------------------------------------------


def test_fr08_cleared_pictures_do_not_stop_finish_and_export(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    made = prepared(sessions, storage, sample)

    with sessions() as session:
        assert assets.rights_problems(assets.resolve(session, made, sample)) == []


def test_fr08_a_picture_whose_rights_are_not_cleared_stops_finish_and_export(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    spec = own_spec(sample)
    spec["assets"][2]["rights_status"] = "needs_review"
    made = prepared(sessions, storage, spec)

    with sessions.begin() as session:
        pictures = by_id(assets.resolve(session, made, spec))
        photo = pictures["a_my_photo"].asset
        assert photo is not None
        photo.rights_status = RightsStatus.BLOCKED
        session.flush()
        problems = assets.rights_problems(assets.resolve(session, made, spec))

    assert problems == [
        "a_harbour needs its rights reviewed before it can be published.",
        "a_my_photo is blocked: its rights do not allow using it.",
    ]


def test_fr08_a_picture_marked_as_someone_elses_work_stops_finish_even_when_cleared(
    sessions: sessionmaker[Session], storage: LocalStorage, sample: dict[str, Any]
) -> None:
    spec = own_spec(sample)
    spec["assets"][2]["contains_third_party_ip"] = True
    made = prepared(sessions, storage, spec)

    with sessions() as session:
        problems = assets.rights_problems(assets.resolve(session, made, spec))

    assert problems == ["a_harbour is marked as containing someone else's work. Replace it."]


def test_fr08_a_picture_without_a_row_fails_closed(
    sessions: sessionmaker[Session], sample: dict[str, Any]
) -> None:
    made = episode(sessions)

    with sessions() as session:
        problems = assets.rights_problems(assets.resolve(session, made, sample))

    assert len(problems) == 4
    assert problems[0] == "a_hill_dawn has no asset yet, so its rights are unknown."
