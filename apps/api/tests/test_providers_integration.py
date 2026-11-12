"""The /providers routes on a real Postgres (sections 3.5 and 10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.providers import DatabaseProviderService
from apps.api.settings import MemorySettingStore
from packages.core import limits
from packages.core.db import models
from packages.core.enums import Provider
from packages.core.settings import Settings

pytestmark = pytest.mark.integration


class Probe:
    def __init__(self) -> None:
        self.called: list[Provider] = []

    def free_check(self, provider: Provider) -> str | None:
        return None

    def tiny_call(self, provider: Provider) -> None:
        self.called.append(provider)


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def probe() -> Probe:
    return Probe()


@pytest.fixture
def client(sessions: sessionmaker[Session], probe: Probe, database_url: str) -> TestClient:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    settings = Settings(database_url=database_url, provider_mode="subscription")
    return TestClient(
        create_app(
            settings,
            checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
            setting_store=MemorySettingStore(),
            provider_service=DatabaseProviderService(sessions, "subscription", probe),
        )
    )


def by_id(body: dict[str, Any], provider: str) -> dict[str, Any]:
    found: dict[str, Any] = next(entry for entry in body["providers"] if entry["id"] == provider)
    return found


def test_fr32_a_stored_budget_changes_the_state_the_overview_shows(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    with sessions.begin() as session:
        for _ in range(4):
            limits.record_usage(session, provider=Provider.CLAUDE_PLAN, model="m")

    before = by_id(client.get("/api/v1/providers").json(), "claude_plan")
    response = client.put(
        "/api/v1/providers/claude_plan/budget", json={"calls_5h": 5, "calls_7d": 150}
    )
    after = by_id(response.json(), "claude_plan")

    assert (before["state"], before["usage"]["five_hours"]["calls"]) == ("ok", 4)
    assert (after["state"], after["budget"]["calls_5h"], after["budget_used"]) == (
        "near_budget",
        5,
        0.8,
    )
    # A number that was not sent keeps its value.
    assert after["budget"]["images_7d"] == before["budget"]["images_7d"]


def test_fr32_a_budget_that_contradicts_the_stored_one_is_refused(client: TestClient) -> None:
    response = client.put("/api/v1/providers/claude_plan/budget", json={"calls_5h": 900})

    assert response.status_code == 409
    assert "calls_5h" in response.json()["error"]["message"]


def test_fr32_continue_anyway_is_stored_for_an_episode_that_exists(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="night_scrolls")
        session.add(channel)
        session.flush()
        episode = models.Episode(channel_id=channel.id, idea="A keeper who climbs a hill.")
        session.add(episode)
        session.flush()
        episode_id = episode.id

    known = client.post(
        "/api/v1/providers/claude_plan/continue", json={"episode_id": str(episode_id)}
    )
    unknown = client.post(
        "/api/v1/providers/claude_plan/continue", json={"episode_id": str(uuid.uuid4())}
    )

    assert (known.status_code, unknown.status_code) == (200, 404)
    with sessions.begin() as session:
        assert limits.is_allowed(session, Provider.CLAUDE_PLAN, episode_id)


def test_fr34_check_now_lifts_a_limit_and_a_second_press_has_to_wait(
    client: TestClient, sessions: sessionmaker[Session], probe: Probe
) -> None:
    with sessions.begin() as session:
        limits.limit_reached(
            session, Provider.CLAUDE_PLAN, message="limit", retry_at=None, now=datetime.now(UTC)
        )

    first = client.post("/api/v1/providers/check")
    second = client.post("/api/v1/providers/check")

    assert by_id(first.json(), "claude_plan")["state"] == "ok"
    assert by_id(first.json(), "claude_plan")["last_checked_at"] is not None
    assert probe.called == [Provider.CLAUDE_PLAN]
    assert second.status_code == 429
    assert 1 <= second.json()["error"]["details"]["retry_after_s"] <= 30
