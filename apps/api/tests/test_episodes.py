"""The episode routes without a database: what a request must look like (section 10)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.episodes import MemoryEpisodeService
from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.providers import MemoryProviderService
from apps.api.settings import MemorySettingStore
from packages.core.settings import Settings


@pytest.fixture
def client() -> TestClient:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    return TestClient(
        create_app(
            Settings(database_url="postgresql+psycopg://vfs:secret@db:5432/vfs"),
            checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
            setting_store=MemorySettingStore(),
            provider_service=MemoryProviderService(),
            episode_service=MemoryEpisodeService(),
        )
    )


def test_an_episode_is_created_from_an_idea_and_can_be_read_back(client: TestClient) -> None:
    created = client.post("/api/v1/episodes", json={"idea": "A baker who gets up at four."})

    body = created.json()
    assert created.status_code == 201
    assert (body["idea"], body["target_duration_s"], body["state"]) == (
        "A baker who gets up at four.",
        45,
        "brief",
    )
    assert client.get(f"/api/v1/episodes/{body['id']}").json() == body
    assert client.get("/api/v1/episodes").json()["total"] == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"idea": ""},
        {"idea": "   "},
        {"idea": 5},
        {"idea": "x" * 4001},
        {"idea": "Fine.", "target_duration_s": 30},
        {"idea": "Fine.", "target_duration_s": "45"},
        {"idea": "Fine.", "start": "yes please"},
        {"idea": "Fine.", "start": 0},
        {"idea": "Fine.", "surprise": 1},
    ],
)
def test_an_episode_needs_an_idea_and_a_length_of_45_or_60(
    client: TestClient, body: dict[str, Any]
) -> None:
    assert client.post("/api/v1/episodes", json=body).status_code == 422


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": "many"}]
)
def test_a_page_of_the_board_has_sensible_bounds(
    client: TestClient, params: dict[str, Any]
) -> None:
    assert client.get("/api/v1/episodes", params=params).status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/reject", {}),
        ("post", "/reject", {"comment": "  "}),
        ("post", "/reject", {"comment": "No.", "return_to_state": "somewhere"}),
        ("post", "/rerun", {"state": "nowhere"}),
        ("post", "/rerun", {}),
        ("post", "/revise", {"comment": ""}),
        ("post", "/revise/apply", {"job_id": "not-an-id"}),
        ("put", "/spec", ["not", "an", "object"]),
    ],
)
def test_a_malformed_request_is_refused_before_anything_is_looked_up(
    client: TestClient, method: str, path: str, body: Any
) -> None:
    response = getattr(client, method)(f"/api/v1/episodes/{uuid.uuid4()}{path}", json=body)

    assert response.status_code == 422


def test_a_diff_needs_both_versions(client: TestClient) -> None:
    url = f"/api/v1/episodes/{uuid.uuid4()}/spec/diff"

    assert client.get(url).status_code == 422
    assert client.get(url, params={"from": 1}).status_code == 422
    assert client.get(url, params={"from": 0, "to": 1}).status_code == 422
    assert client.get(url, params={"from": 1, "to": 2}).status_code == 404


def test_an_id_that_is_not_an_id_is_refused(client: TestClient) -> None:
    assert client.get("/api/v1/episodes/not-an-id").status_code == 422
