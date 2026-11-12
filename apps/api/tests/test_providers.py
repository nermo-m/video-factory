"""The /providers routes (design doc sections 3.5 and 10, FR-31, FR-32, FR-34)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.episodes import MemoryEpisodeService
from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.providers import MemoryProviderService, UnknownEpisodeError
from apps.api.settings import MemorySettingStore
from packages.core import limits
from packages.core.enums import Billing, Provider, ProviderState, StatusSource
from packages.core.settings import Settings

UNTIL = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
CHECKED = datetime(2026, 11, 12, 13, 0, tzinfo=UTC)


def claude_view(**changes: Any) -> limits.ProviderView:
    fields: dict[str, Any] = {
        "provider": Provider.CLAUDE_PLAN,
        "title": "Claude plan",
        "billing": Billing.PLAN,
        "state": ProviderState.LIMITED,
        "state_source": StatusSource.TOOL,
        "limited_until": UNTIL,
        "last_checked_at": CHECKED,
        "last_error": "You've hit your session limit",
        "usage": limits.Windows(
            five_hours=limits.Usage(calls=4, input_tokens=900, output_tokens=120),
            seven_days=limits.Usage(calls=31, images=2, input_tokens=9000, output_tokens=800),
        ),
        "budget": limits.Budget(calls_5h=20, calls_7d=150, images_5h=5, images_7d=30),
        "share": 0.2067,
    }
    return limits.ProviderView(**{**fields, **changes})


class Service(MemoryProviderService):
    """Remembers what it was asked to do."""

    def __init__(self) -> None:
        super().__init__([claude_view()])
        self.budgets: list[tuple[Provider, dict[str, Any]]] = []
        self.continued: list[tuple[Provider, uuid.UUID]] = []
        self.too_soon = False
        self.known_episodes: set[uuid.UUID] = set()

    def set_budget(self, provider: Provider, numbers: dict[str, Any]) -> None:
        limits.budget_from_json(numbers, provider)
        self.budgets.append((provider, numbers))

    def continue_anyway(self, provider: Provider, episode_id: uuid.UUID) -> None:
        if episode_id not in self.known_episodes:
            raise UnknownEpisodeError(str(episode_id))
        self.continued.append((provider, episode_id))

    def check_now(self) -> list[limits.ProviderView]:
        if self.too_soon:
            raise limits.CheckTooSoonError(20)
        return self.views


@pytest.fixture
def service() -> Service:
    return Service()


@pytest.fixture
def client(service: Service) -> TestClient:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    settings = Settings(
        database_url="postgresql+psycopg://vfs:secret@db:5432/vfs", provider_mode="subscription"
    )
    return TestClient(
        create_app(
            settings,
            checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
            setting_store=MemorySettingStore(),
            provider_service=service,
            episode_service=MemoryEpisodeService(),
        )
    )


def test_fr31_the_overview_shows_state_usage_and_budget_and_says_who_counted(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/providers")

    assert response.status_code == 200
    assert response.json() == {
        "providers": [
            {
                "id": "claude_plan",
                "title": "Claude plan",
                "billing": "plan",
                "state": "limited",
                "state_source": "tool",
                "limited_until": "2026-11-12T15:00:00Z",
                "last_checked_at": "2026-11-12T13:00:00Z",
                "last_error": "You've hit your session limit",
                "usage": {
                    "five_hours": {
                        "calls": 4,
                        "images": 0,
                        "input_tokens": 900,
                        "output_tokens": 120,
                        "cost_usd": "0",
                    },
                    "seven_days": {
                        "calls": 31,
                        "images": 2,
                        "input_tokens": 9000,
                        "output_tokens": 800,
                        "cost_usd": "0",
                    },
                },
                "usage_source": "app",
                "budget": {
                    "calls_5h": 20,
                    "calls_7d": 150,
                    "images_5h": 5,
                    "images_7d": 30,
                    "usd_5h": "0",
                    "usd_7d": "0",
                },
                "budget_used": 0.2067,
            }
        ]
    }


def test_fr32_a_budget_is_set_with_the_numbers_that_were_sent(
    client: TestClient, service: Service
) -> None:
    response = client.put(
        "/api/v1/providers/claude_plan/budget", json={"calls_5h": 10, "calls_7d": 80}
    )

    assert response.status_code == 200
    assert service.budgets == [(Provider.CLAUDE_PLAN, {"calls_5h": 10, "calls_7d": 80})]
    assert response.json()["providers"][0]["id"] == "claude_plan"


def test_fr32_a_dollar_budget_keeps_its_exact_amount(client: TestClient, service: Service) -> None:
    client.put("/api/v1/providers/claude_plan/budget", json={"usd_5h": "0.10", "usd_7d": "2.5"})

    (_, numbers) = service.budgets[0]
    assert (Decimal(numbers["usd_5h"]), Decimal(numbers["usd_7d"])) == (
        Decimal("0.10"),
        Decimal("2.5"),
    )


@pytest.mark.parametrize(
    "body",
    [
        {"calls_5h": -1},
        {"calls_5h": 2.5},
        {"calls_5h": "ten"},
        {"calls_5h": True},
        {"surprise": 1},
        {"usd_5h": 1.5},
        {"usd_5h": "-1"},
        {"usd_5h": "a lot"},
    ],
)
def test_fr32_a_budget_that_makes_no_sense_is_refused(
    client: TestClient, service: Service, body: dict[str, Any]
) -> None:
    response = client.put("/api/v1/providers/claude_plan/budget", json=body)

    assert response.status_code == 422
    assert service.budgets == []


def test_a_budget_rule_that_is_broken_says_which_one(client: TestClient) -> None:
    response = client.put(
        "/api/v1/providers/claude_plan/budget", json={"calls_5h": 50, "calls_7d": 5}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_budget"
    assert "calls_5h" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "/api/v1/providers/anthropic_api/budget", {"usd_5h": "1"}),
        ("post", "/api/v1/providers/demo/continue", {"episode_id": str(uuid.uuid4())}),
    ],
)
def test_a_provider_of_another_mode_cannot_be_changed(
    client: TestClient, method: str, path: str, body: dict[str, Any]
) -> None:
    response = getattr(client, method)(path, json=body)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "provider_not_in_use"


def test_a_provider_that_does_not_exist_is_refused(client: TestClient) -> None:
    assert client.put("/api/v1/providers/someone_else/budget", json={}).status_code == 422


def test_fr32_continue_anyway_names_the_episode(client: TestClient, service: Service) -> None:
    episode = uuid.uuid4()
    service.known_episodes.add(episode)

    response = client.post(
        "/api/v1/providers/claude_plan/continue", json={"episode_id": str(episode)}
    )

    assert response.status_code == 200
    assert service.continued == [(Provider.CLAUDE_PLAN, episode)]


def test_fr32_continue_anyway_for_an_unknown_episode_is_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/v1/providers/claude_plan/continue", json={"episode_id": str(uuid.uuid4())}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "episode_not_found"


@pytest.mark.parametrize("body", [{}, {"episode_id": "not-an-id"}, {"episode_id": None}])
def test_continue_anyway_needs_an_episode(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/v1/providers/claude_plan/continue", json=body).status_code == 422


def test_fr34_check_now_returns_the_fresh_status(client: TestClient) -> None:
    response = client.post("/api/v1/providers/check")

    assert response.status_code == 200
    assert response.json()["providers"][0]["last_checked_at"] == "2026-11-12T13:00:00Z"


def test_fr34_check_now_twice_within_30_seconds_is_refused_with_the_wait(
    client: TestClient, service: Service
) -> None:
    service.too_soon = True

    response = client.post("/api/v1/providers/check")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "checked_too_recently"
    assert response.json()["error"]["details"] == {"retry_after_s": 20}


def test_demo_mode_lists_its_recordings_as_a_provider_without_limits() -> None:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    client = TestClient(
        create_app(
            Settings(database_url="postgresql+psycopg://vfs:secret@db:5432/vfs"),
            checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
            setting_store=MemorySettingStore(),
            provider_service=MemoryProviderService(),
            episode_service=MemoryEpisodeService(),
        )
    )

    (demo,) = client.get("/api/v1/providers").json()["providers"]

    assert (demo["id"], demo["billing"], demo["state"]) == ("demo", "demo", "ok")
    assert demo["budget_used"] == 0.0
