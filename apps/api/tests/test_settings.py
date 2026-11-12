"""GET and PUT /api/v1/settings (design doc sections 3.4 and 10).

Non-secret settings only. The response shows which secrets are present, never their
values, and whether paid APIs are really on: that takes the mode and the switch together.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.providers import MemoryProviderService
from apps.api.settings import MemorySettingStore
from packages.core.settings import Settings

DATABASE_URL = "postgresql+psycopg://vfs:super-secret-password@db:5432/vfs"
PLANTED = "planted-key-that-must-never-leave-the-server"


def make_client(
    *, provider_mode: str = "demo", store: MemorySettingStore | None = None
) -> TestClient:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    settings = Settings(database_url=DATABASE_URL, provider_mode=provider_mode)
    checks = HealthChecks(database=ok, storage=ok, comfyui=ok)
    return TestClient(
        create_app(
            settings,
            checks=checks,
            setting_store=store or MemorySettingStore(),
            provider_service=MemoryProviderService(),
        )
    )


def test_settings_show_the_mode_and_that_paid_apis_are_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    response = make_client().get("/api/v1/settings")

    assert response.status_code == 200
    assert response.json() == {
        "provider_mode": "demo",
        "use_paid_apis": False,
        "paid_apis_active": False,
        "paid_apis_message": (
            "Paid APIs are off: PROVIDER_MODE is 'demo', not 'api' and the 'Use paid APIs' "
            "switch in Settings is off. Both are needed, and the app never switches to a "
            "paid API by itself."
        ),
        "secrets": {"ANTHROPIC_API_KEY": False, "OPENAI_API_KEY": False},
    }


def test_nfr01_settings_say_that_a_key_is_present_but_never_show_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    response = make_client().get("/api/v1/settings")

    assert response.json()["secrets"] == {"ANTHROPIC_API_KEY": True, "OPENAI_API_KEY": False}
    assert PLANTED not in response.text
    assert "super-secret-password" not in response.text


def test_the_owner_can_switch_paid_apis_on_and_off() -> None:
    client = make_client(provider_mode="api")

    switched_on = client.put("/api/v1/settings", json={"use_paid_apis": True})

    assert switched_on.status_code == 200
    assert switched_on.json()["use_paid_apis"] is True
    assert switched_on.json()["paid_apis_active"] is True
    assert switched_on.json()["paid_apis_message"] is None
    assert client.get("/api/v1/settings").json()["paid_apis_active"] is True

    switched_off = client.put("/api/v1/settings", json={"use_paid_apis": False})

    assert switched_off.json()["paid_apis_active"] is False
    assert "switch in Settings is off" in switched_off.json()["paid_apis_message"]


@pytest.mark.parametrize("mode", ["demo", "subscription"])
def test_fr28_the_switch_alone_does_not_turn_paid_apis_on(mode: str) -> None:
    client = make_client(provider_mode=mode)

    body = client.put("/api/v1/settings", json={"use_paid_apis": True}).json()

    assert body["use_paid_apis"] is True
    assert body["paid_apis_active"] is False
    assert f"PROVIDER_MODE is '{mode}', not 'api'" in body["paid_apis_message"]
    # The mode is not something this API can change.
    assert body["provider_mode"] == mode


def test_fr28_the_mode_cannot_be_set_through_the_api() -> None:
    client = make_client(provider_mode="subscription")

    response = client.put("/api/v1/settings", json={"use_paid_apis": False, "provider_mode": "api"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert client.get("/api/v1/settings").json()["provider_mode"] == "subscription"


@pytest.mark.parametrize("body", [{}, {"use_paid_apis": "yes"}, {"use_paid_apis": 1}])
def test_the_switch_must_be_a_plain_true_or_false(body: dict[str, object]) -> None:
    response = make_client().put("/api/v1/settings", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_a_method_the_address_does_not_support_names_every_method_it_does() -> None:
    response = make_client().delete("/api/v1/settings")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    # Both routes at this address count, not only the first one registered.
    assert response.headers["allow"] == "GET, PUT"


def test_a_body_that_is_not_json_is_a_documented_bad_request() -> None:
    client = make_client()

    response = client.put(
        "/api/v1/settings", content=b"\xff\xfe{", headers={"content-type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"
    documented = client.get("/api/v1/openapi.json").json()["paths"]["/api/v1/settings"]["put"]
    assert "400" in documented["responses"]
