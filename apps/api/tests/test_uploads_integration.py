"""The owner's own pictures on a real Postgres: `POST /episodes/{id}/assets/{asset}/upload`
and `POST /episodes/{id}/assets/match` (design doc section 10, FR-07, section 4.2)."""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.episodes import DatabaseEpisodeService
from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.providers import MemoryProviderService
from apps.api.settings import MemorySettingStore
from packages.adapters.storage import LocalStorage
from packages.core import assets, queue, uploads
from packages.core.db import models
from packages.core.enums import JobTag, RightsStatus, SpecAuthor
from packages.core.settings import Settings
from packages.core.specs import store_spec
from packages.core.tests.test_assets import own_spec, sample

pytestmark = pytest.mark.integration

__all__ = ["sample"]

PNG = {"content-type": "image/png"}


def picture(size: tuple[int, int] = (900, 1600), kind: str = "PNG", shade: int = 90) -> bytes:
    stored = io.BytesIO()
    Image.new("RGB", size, (40, shade, 160)).save(stored, format=kind)
    return stored.getvalue()


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client(sessions: sessionmaker[Session], database_url: str, data_dir: Path) -> TestClient:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    return TestClient(
        create_app(
            Settings(database_url=database_url, data_dir=str(data_dir)),
            checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
            setting_store=MemorySettingStore(),
            provider_service=MemoryProviderService(),
            episode_service=DatabaseEpisodeService(sessions, storage=LocalStorage(data_dir)),
        )
    )


@pytest.fixture
def spec(sample: dict[str, Any]) -> dict[str, Any]:
    return own_spec(sample)


@pytest.fixture
def episode_id(sessions: sessionmaker[Session], spec: dict[str, Any], data_dir: Path) -> uuid.UUID:
    """An episode with two library pictures, one to generate and one to upload."""
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="night_scrolls")
        session.add(channel)
        session.flush()
        episode = models.Episode(channel_id=channel.id, idea="A keeper who climbs a hill.")
        session.add(episode)
        session.flush()
        store_spec(session, episode.id, spec, author=SpecAuthor.MODEL)
        assets.ensure_library(session, LocalStorage(data_dir), channel.id)
        return episode.id


def listed(body: dict[str, Any], asset_id: str) -> dict[str, Any]:
    return next(item for item in body["assets"] if item["id"] == asset_id)


def upload(
    client: TestClient, episode_id: uuid.UUID, asset_id: str, data: bytes, **headers: str
) -> Any:
    return client.post(
        f"/api/v1/episodes/{episode_id}/assets/{asset_id}/upload",
        content=data,
        headers=headers or PNG,
    )


def test_fr07_an_uploaded_picture_becomes_the_file_of_its_picture(
    client: TestClient, episode_id: uuid.UUID, data_dir: Path
) -> None:
    before = listed(client.get(f"/api/v1/episodes/{episode_id}/assets").json(), "a_my_photo")
    assert (before["resolved"], before["uploaded"]) == (False, False)

    response = upload(
        client, episode_id, "a_my_photo", picture(kind="JPEG"), **{"content-type": "image/jpeg"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    mine = listed(body, "a_my_photo")
    assert (mine["resolved"], mine["uploaded"], mine["versions"]) == (True, True, 1)
    assert (mine["model"], mine["licence"]) == (None, uploads.UPLOAD_LICENCE)
    assert mine["rights_status"] == "needs_review"
    assert body["unresolved"] == 1, "only the picture that is still to be generated"
    assert mine["image_url"].startswith(f"/api/v1/files/episodes/{episode_id}/uploads/a_my_photo/")
    served = client.get(mine["image_url"])
    assert served.status_code == 200
    stored = Image.open(io.BytesIO(served.content))
    assert (stored.format, stored.size) == ("PNG", (900, 1600))


def test_an_upload_replaces_a_generated_picture_and_keeps_the_earlier_file(
    client: TestClient,
    sessions: sessionmaker[Session],
    episode_id: uuid.UUID,
    spec: dict[str, Any],
) -> None:
    with sessions.begin() as session:
        episode = session.get_one(models.Episode, episode_id)
        assets.sync(session, episode, spec)
        harbour = next(p for p in assets.resolve(session, episode, spec) if p.id == "a_harbour")
        assert harbour.asset is not None
        assets.add_version(
            session,
            harbour.asset,
            file_path="jobs/gen.image/aa/one/a_harbour.png",
            prompt="A harbour.",
            model="codex image tool",
        )
        harbour.asset.rights_status = RightsStatus.CLEARED

    response = upload(client, episode_id, "a_harbour", picture())

    now = listed(response.json(), "a_harbour")
    assert response.status_code == 200
    assert (now["origin"], now["uploaded"], now["versions"]) == ("generated", True, 2)
    assert now["image_url"] != "/api/v1/files/jobs/gen.image/aa/one/a_harbour.png"
    # The rights of the generated file say nothing about the owner's file.
    assert now["rights_status"] == "needs_review"
    with sessions() as session:
        episode = session.get_one(models.Episode, episode_id)
        again = next(p for p in assets.resolve(session, episode, spec) if p.id == "a_harbour")
        assert again.asset is not None
        kept = [version.file_path for version in assets.versions(session, again.asset)]
    assert kept[0] == "jobs/gen.image/aa/one/a_harbour.png", "nothing is deleted"


def test_the_same_picture_uploaded_twice_is_one_file_and_two_versions(
    client: TestClient, episode_id: uuid.UUID, data_dir: Path
) -> None:
    first = upload(client, episode_id, "a_my_photo", picture()).json()
    second = upload(client, episode_id, "a_my_photo", picture()).json()

    one, two = listed(first, "a_my_photo"), listed(second, "a_my_photo")
    assert one["image_url"] == two["image_url"]
    assert two["versions"] == 2
    assert len(list((data_dir / "episodes" / str(episode_id) / "uploads").rglob("*.png"))) == 1


def test_section_4_2_an_upload_marks_a_video_that_shows_the_picture_out_of_date(
    client: TestClient,
    sessions: sessionmaker[Session],
    episode_id: uuid.UUID,
    spec: dict[str, Any],
) -> None:
    upload(client, episode_id, "a_my_photo", picture())
    assert client.get(f"/api/v1/episodes/{episode_id}").json()["stale_from_state"] is None
    # The episode has a video: a render job of it has succeeded.
    with sessions.begin() as session:
        queue.enqueue(
            session,
            job_type="render.join",
            tag=JobTag.CPU,
            payload={"state": "render", "stage": 1, "run": 1},
            episode_id=episode_id,
        )
    with sessions.begin() as session:
        claim = queue.claim_next(session, JobTag.CPU)
        assert claim is not None
        queue.complete(session, claim, {})

    upload(client, episode_id, "a_my_photo", picture(shade=200))

    shown = [s["id"] for s in spec["scenes"] if s.get("visual", {}).get("asset_id") == "a_my_photo"]
    detail = client.get(f"/api/v1/episodes/{episode_id}").json()
    assert shown
    assert detail["stale_from_state"] == "render"
    assert detail["stale_scenes"] == {"voice": [], "render": shown}


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (b"this is not a picture", 422, "not_a_picture"),
        (b"", 422, "not_a_picture"),
        (picture(size=(120, 200)), 422, "too_small"),
    ],
)
def test_a_file_that_is_not_a_usable_picture_is_refused_and_nothing_is_stored(
    client: TestClient, episode_id: uuid.UUID, data_dir: Path, data: bytes, status: int, code: str
) -> None:
    response = upload(client, episode_id, "a_my_photo", data)

    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert not (data_dir / "episodes").exists()
    after = listed(client.get(f"/api/v1/episodes/{episode_id}/assets").json(), "a_my_photo")
    assert (after["resolved"], after["versions"]) == (False, 0)


def test_a_file_over_the_size_limit_is_refused_without_being_read_whole(
    client: TestClient, episode_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(uploads, "MAX_BYTES", 2000)

    response = upload(client, episode_id, "a_my_photo", picture() + b"\0" * 3000)

    assert (response.status_code, response.json()["error"]["code"]) == (413, "too_large")


@pytest.mark.parametrize(
    "sent_as", ["text/html", "image/gif", "image/svg+xml", "multipart/form-data"]
)
def test_a_file_that_is_not_sent_as_a_picture_is_refused(
    client: TestClient, episode_id: uuid.UUID, sent_as: str
) -> None:
    response = upload(client, episode_id, "a_my_photo", picture(), **{"content-type": sent_as})

    assert (response.status_code, response.json()["error"]["code"]) == (415, "unsupported_type")


def test_a_library_picture_cannot_be_replaced_for_one_episode(
    client: TestClient, episode_id: uuid.UUID
) -> None:
    response = upload(client, episode_id, "a_hill_dawn", picture())

    assert (response.status_code, response.json()["error"]["code"]) == (409, "library_picture")


def test_an_unknown_picture_or_episode_is_not_found(
    client: TestClient, episode_id: uuid.UUID
) -> None:
    no_picture = upload(client, episode_id, "a_nowhere", picture())
    no_episode = upload(client, uuid.uuid4(), "a_my_photo", picture())
    bad_id = upload(client, episode_id, "..%2F..%2Fetc", picture())

    assert (no_picture.status_code, no_picture.json()["error"]["code"]) == (404, "asset_not_found")
    assert (no_episode.status_code, no_episode.json()["error"]["code"]) == (
        404,
        "episode_not_found",
    )
    assert bad_id.status_code in (404, 422)


def test_a_picture_that_is_being_made_cannot_be_uploaded_over(
    client: TestClient, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session:
        queue.enqueue(
            session,
            job_type="gen.image",
            tag=JobTag.CPU,
            payload={"asset_id": "a_harbour"},
            episode_id=episode_id,
        )

    response = upload(client, episode_id, "a_harbour", picture())

    assert (response.status_code, response.json()["error"]["code"]) == (409, "already_generating")


# --- matching by file name (FR-07) ---------------------------------------------------------


def test_fr07_file_names_are_matched_to_the_pictures_of_the_episode_and_nothing_is_stored(
    client: TestClient, episode_id: uuid.UUID, data_dir: Path
) -> None:
    response = client.post(
        f"/api/v1/episodes/{episode_id}/assets/match",
        json={"filenames": ["Harbour.JPG", "holiday.png", "a_hill_dawn.png", "my-photo.webp"]},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "matches": [
            {"filename": "Harbour.JPG", "asset_id": "a_harbour", "why": None},
            {
                "filename": "holiday.png",
                "asset_id": None,
                "why": "No picture of this episode has this name.",
            },
            # A library picture cannot be replaced, so no file is matched to it.
            {
                "filename": "a_hill_dawn.png",
                "asset_id": None,
                "why": "No picture of this episode has this name.",
            },
            {"filename": "my-photo.webp", "asset_id": "a_my_photo", "why": None},
        ]
    }
    assert not (data_dir / "episodes").exists()


@pytest.mark.parametrize(
    "body", [{}, {"filenames": []}, {"filenames": [""]}, {"filenames": ["a.png"] * 201}]
)
def test_fr07_a_match_request_without_usable_names_is_refused(
    client: TestClient, episode_id: uuid.UUID, body: dict[str, Any]
) -> None:
    response = client.post(f"/api/v1/episodes/{episode_id}/assets/match", json=body)

    assert response.status_code == 422


def test_fr07_matching_for_an_unknown_episode_is_not_found(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/episodes/{uuid.uuid4()}/assets/match", json={"filenames": ["a.png"]}
    )

    assert response.status_code == 404
