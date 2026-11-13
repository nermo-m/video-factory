"""`GET /episodes/{id}/assets` on a real Postgres (design doc section 10, FR-05, FR-08)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.episodes import DatabaseEpisodeService
from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.providers import MemoryProviderService
from apps.api.settings import MemorySettingStore
from packages.adapters.storage import LocalStorage
from packages.core import assets
from packages.core.db import models
from packages.core.enums import SpecAuthor
from packages.core.settings import Settings
from packages.core.specs import store_spec
from packages.core.tests.test_assets import own_spec, sample

pytestmark = pytest.mark.integration

__all__ = ["sample"]


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def client(sessions: sessionmaker[Session], database_url: str) -> TestClient:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    return TestClient(
        create_app(
            Settings(database_url=database_url),
            checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
            setting_store=MemorySettingStore(),
            provider_service=MemoryProviderService(),
            episode_service=DatabaseEpisodeService(sessions),
        )
    )


@pytest.fixture
def episode_id(
    sessions: sessionmaker[Session], sample: dict[str, Any], tmp_path: Path
) -> uuid.UUID:
    """An episode with two library pictures, one to generate and one to upload."""
    spec = own_spec(sample)
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="night_scrolls")
        session.add(channel)
        session.flush()
        episode = models.Episode(channel_id=channel.id, idea="A keeper who climbs a hill.")
        session.add(episode)
        session.flush()
        store_spec(session, episode.id, spec, author=SpecAuthor.MODEL)
        assets.ensure_library(session, LocalStorage(tmp_path / "data"), channel.id)
        assets.sync(session, episode, spec)
        return episode.id


def test_the_pictures_of_an_episode_are_listed_with_where_they_come_from_and_their_file(
    client: TestClient,
    sessions: sessionmaker[Session],
    episode_id: uuid.UUID,
    sample: dict[str, Any],
) -> None:
    spec = own_spec(sample)
    with sessions.begin() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        harbour = next(
            picture
            for picture in assets.resolve(session, episode, spec)
            if picture.id == "a_harbour"
        )
        assert harbour.asset is not None
        assets.add_version(
            session,
            harbour.asset,
            file_path="jobs/gen.image/aa/one/a_harbour.png",
            prompt="A harbour.",
            model="codex image tool",
        )

    response = client.get(f"/api/v1/episodes/{episode_id}/assets")

    body = response.json()
    listed = {item["id"]: item for item in body["assets"]}
    assert response.status_code == 200
    assert list(listed) == ["a_hill_dawn", "a_lamp_room", "a_harbour", "a_my_photo"]
    assert listed["a_hill_dawn"] == {
        "id": "a_hill_dawn",
        "kind": "image",
        "origin": "library",
        "used_in": ["s02_climb"],
        "becomes_clip": False,
        "prompt": None,
        "filename": None,
        "resolved": True,
        "generating": False,
        "image_url": "/api/v1/files/library/a_hill_dawn/v1.png",
        "model": None,
        "versions": 1,
        "licence": "MIT",
        "rights_status": "cleared",
        "contains_third_party_ip": False,
    }
    assert listed["a_harbour"]["origin"] == "generated"
    assert listed["a_harbour"]["becomes_clip"] is True
    assert listed["a_harbour"]["prompt"] == "Prompt in the spec for a_harbour."
    assert listed["a_harbour"]["image_url"] == "/api/v1/files/jobs/gen.image/aa/one/a_harbour.png"
    assert (listed["a_harbour"]["model"], listed["a_harbour"]["versions"]) == (
        "codex image tool",
        1,
    )
    assert listed["a_my_photo"]["origin"] == "uploaded"
    assert (listed["a_my_photo"]["resolved"], listed["a_my_photo"]["image_url"]) == (False, None)
    assert body["unresolved"] == 1
    assert body["rights_problems"] == []


def test_an_episode_without_a_plan_has_no_pictures_to_list(
    client: TestClient, episode_id: uuid.UUID
) -> None:
    created = client.post("/api/v1/episodes", json={"idea": "A baker.", "start": False}).json()

    no_plan = client.get(f"/api/v1/episodes/{created['id']}/assets")
    unknown = client.get(f"/api/v1/episodes/{uuid.uuid4()}/assets")

    assert no_plan.status_code == 404
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "episode_not_found"


# --- make a picture again ------------------------------------------------------------------


def test_fr06_make_again_queues_one_picture_job_and_the_picture_says_it_is_being_made(
    client: TestClient, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    response = client.post(
        f"/api/v1/episodes/{episode_id}/assets/a_harbour/regenerate",
        json={"note": "Make it dawn, not dusk."},
    )

    listed = {item["id"]: item for item in response.json()["assets"]}
    with sessions() as session:
        job = session.scalars(select(models.Job)).one()
    assert response.status_code == 202
    assert listed["a_harbour"]["generating"] is True
    assert listed["a_hill_dawn"]["generating"] is False
    assert (job.type, job.episode_id) == ("gen.image", episode_id)
    assert job.input == {
        "asset_id": "a_harbour",
        "regenerate": True,
        "note": "Make it dawn, not dusk.",
    }


def test_make_again_without_a_note_sends_none(
    client: TestClient, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    response = client.post(f"/api/v1/episodes/{episode_id}/assets/a_harbour/regenerate", json={})

    with sessions() as session:
        job = session.scalars(select(models.Job)).one()
    assert response.status_code == 202
    assert job.input == {"asset_id": "a_harbour", "regenerate": True}


def test_a_picture_that_is_already_being_made_is_not_queued_twice(
    client: TestClient, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    client.post(f"/api/v1/episodes/{episode_id}/assets/a_harbour/regenerate", json={})

    again = client.post(f"/api/v1/episodes/{episode_id}/assets/a_harbour/regenerate", json={})

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_generating"
    with sessions() as session:
        assert len(session.scalars(select(models.Job)).all()) == 1


@pytest.mark.parametrize("asset_id", ["a_hill_dawn", "a_my_photo"])
def test_only_a_generated_picture_can_be_made_again(
    client: TestClient, episode_id: uuid.UUID, asset_id: str
) -> None:
    response = client.post(f"/api/v1/episodes/{episode_id}/assets/{asset_id}/regenerate", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_generated"


def test_a_picture_the_episode_does_not_have_is_not_found(
    client: TestClient, episode_id: uuid.UUID
) -> None:
    response = client.post(f"/api/v1/episodes/{episode_id}/assets/a_nowhere/regenerate", json={})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "asset_not_found"


@pytest.mark.parametrize(
    "body", [{"note": "x" * 501}, {"note": 5}, {"note": "ok", "prompt": "another field"}]
)
def test_a_request_that_is_not_right_is_refused(
    client: TestClient, episode_id: uuid.UUID, body: dict[str, object]
) -> None:
    response = client.post(f"/api/v1/episodes/{episode_id}/assets/a_harbour/regenerate", json=body)

    assert response.status_code == 422
