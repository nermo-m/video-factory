"""`GET /episodes/{id}/renders` and the episode's `resting` flag on a real Postgres
(design doc sections 4.1 and 10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.episodes import DatabaseEpisodeService
from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.providers import MemoryProviderService
from apps.api.settings import MemorySettingStore
from packages.core import queue
from packages.core.db import models
from packages.core.enums import EpisodeState, JobTag, RenderKind, SpecAuthor, SpecKind
from packages.core.settings import Settings

pytestmark = pytest.mark.integration


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
def episode_id(sessions: sessionmaker[Session]) -> uuid.UUID:
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="night_scrolls")
        session.add(channel)
        session.flush()
        episode = models.Episode(
            channel_id=channel.id, idea="A keeper who climbs a hill.", state=EpisodeState.RENDER
        )
        session.add(episode)
        session.flush()
        return episode.id


def spec(
    session: Session,
    episode_id: uuid.UUID,
    version: int,
    kind: SpecKind,
    parent: models.SpecVersion | None = None,
) -> models.SpecVersion:
    stored = models.SpecVersion(
        episode_id=episode_id,
        version=version,
        kind=kind,
        body={"scenes": []},
        author=SpecAuthor.MODEL,
        parent_id=parent.id if parent else None,
    )
    session.add(stored)
    session.flush()
    return stored


def render(
    session: Session,
    episode_id: uuid.UUID,
    resolved: models.SpecVersion,
    folder: str,
    made: datetime,
    **fields: Any,
) -> models.Render:
    stored = models.Render(
        episode_id=episode_id,
        resolved_spec_id=resolved.id,
        kind=RenderKind.DRAFT,
        file_path=f"jobs/render.join/{folder}/video.mp4",
        contact_sheet_path=f"jobs/render.join/{folder}/video_contact_sheet.jpg",
        duration_s=44.25,
        created_at=made,
        **fields,
    )
    session.add(stored)
    session.flush()
    return stored


def test_the_renders_of_an_episode_are_listed_newest_first_with_their_addresses(
    client: TestClient, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    noon = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    with sessions.begin() as session:
        first_plan = spec(session, episode_id, 1, SpecKind.AUTHORED)
        first_resolved = spec(session, episode_id, 2, SpecKind.RESOLVED, first_plan)
        second_plan = spec(session, episode_id, 3, SpecKind.AUTHORED, first_plan)
        second_resolved = spec(session, episode_id, 4, SpecKind.RESOLVED, second_plan)
        older = render(session, episode_id, first_resolved, "aa/one", noon)
        newer = render(session, episode_id, second_resolved, "bb/two", noon + timedelta(hours=1))

    response = client.get(f"/api/v1/episodes/{episode_id}/renders")

    body = response.json()
    assert response.status_code == 200
    assert (body["total"], body["limit"], body["offset"]) == (2, 24, 0)
    assert [item["id"] for item in body["renders"]] == [str(newer.id), str(older.id)]
    latest = body["renders"][0]
    assert latest["kind"] == "draft"
    assert latest["duration_s"] == 44.25
    assert latest["video_url"] == "/api/v1/files/jobs/render.join/bb/two/video.mp4"
    assert (
        latest["contact_sheet_url"]
        == "/api/v1/files/jobs/render.join/bb/two/video_contact_sheet.jpg"
    )
    assert latest["spec_version"] == 3, "the version of the plan it was rendered from"
    assert body["renders"][1]["spec_version"] == 1
    assert latest["created_at"].startswith("2026-11-12T13:00:00")


def test_the_renders_are_paged(
    client: TestClient, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    noon = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    with sessions.begin() as session:
        plan = spec(session, episode_id, 1, SpecKind.AUTHORED)
        resolved = spec(session, episode_id, 2, SpecKind.RESOLVED, plan)
        made = [
            render(session, episode_id, resolved, f"aa/{n}", noon + timedelta(minutes=n))
            for n in range(3)
        ]

    page = client.get(f"/api/v1/episodes/{episode_id}/renders?limit=2&offset=1").json()

    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 1)
    assert [item["id"] for item in page["renders"]] == [str(made[1].id), str(made[0].id)]


def test_a_render_without_a_file_has_no_address(
    client: TestClient, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session:
        plan = spec(session, episode_id, 1, SpecKind.AUTHORED)
        resolved = spec(session, episode_id, 2, SpecKind.RESOLVED, plan)
        session.add(
            models.Render(
                episode_id=episode_id, resolved_spec_id=resolved.id, kind=RenderKind.PREVIEW
            )
        )

    only = client.get(f"/api/v1/episodes/{episode_id}/renders").json()["renders"][0]

    assert (only["video_url"], only["contact_sheet_url"], only["duration_s"]) == (None, None, None)


def test_an_episode_without_renders_has_an_empty_list_and_an_unknown_one_is_not_found(
    client: TestClient, episode_id: uuid.UUID
) -> None:
    empty = client.get(f"/api/v1/episodes/{episode_id}/renders")
    unknown = client.get(f"/api/v1/episodes/{uuid.uuid4()}/renders")

    assert empty.json() == {"renders": [], "total": 0, "limit": 24, "offset": 0}
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "episode_not_found"


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=many"])
def test_a_page_that_makes_no_sense_is_refused(
    client: TestClient, episode_id: uuid.UUID, query: str
) -> None:
    assert client.get(f"/api/v1/episodes/{episode_id}/renders?{query}").status_code == 422


# --- resting -----------------------------------------------------------------------------


def join_job(sessions: sessionmaker[Session], episode_id: uuid.UUID, *, finish: bool) -> None:
    """The last job of the render state, queued or succeeded."""
    with sessions.begin() as session:
        queue.enqueue(
            session,
            job_type="render.join",
            tag=JobTag.CPU,
            payload={"state": "render", "stage": 1, "run": 1},
            episode_id=episode_id,
        )
    if finish:
        with sessions.begin() as session:
            claim = queue.claim_next(session, JobTag.CPU)
            assert claim is not None
            queue.complete(session, claim, {"ok": True})


def test_an_episode_whose_video_is_rendered_says_that_it_rests(
    client: TestClient, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    join_job(sessions, episode_id, finish=True)

    detail = client.get(f"/api/v1/episodes/{episode_id}").json()
    listed = client.get("/api/v1/episodes").json()["episodes"][0]

    assert (detail["state"], detail["resting"]) == ("render", True)
    assert listed["resting"] is True


def test_an_episode_that_is_still_rendering_does_not_rest(
    client: TestClient, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    join_job(sessions, episode_id, finish=False)

    assert client.get(f"/api/v1/episodes/{episode_id}").json()["resting"] is False


def test_an_episode_in_an_earlier_state_does_not_rest(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    created = client.post("/api/v1/episodes", json={"idea": "A baker.", "start": False}).json()

    assert created["resting"] is False
