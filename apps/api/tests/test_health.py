"""GET /api/v1/health (design doc section 10): liveness, database, storage, ComfyUI
reachability and the demo mode flag."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from packages.core.settings import Settings

DATABASE_URL = "postgresql+psycopg://vfs:super-secret-password@db:5432/vfs"


def ok() -> Check:
    return Check(status=CheckStatus.OK)


def make_client(
    *,
    provider_mode: str = "demo",
    database: Check | None = None,
    storage: Check | None = None,
    comfyui: Check | None = None,
) -> TestClient:
    settings = Settings(database_url=DATABASE_URL, provider_mode=provider_mode)
    checks = HealthChecks(
        database=lambda: database or ok(),
        storage=lambda: storage or ok(),
        comfyui=lambda: comfyui or ok(),
    )
    return TestClient(create_app(settings, checks=checks))


def test_health_reports_every_check_and_demo_mode() -> None:
    response = make_client().get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "provider_mode": "demo",
        "demo_mode": True,
        "checks": {
            "database": {"status": "ok", "message": None},
            "storage": {"status": "ok", "message": None},
            "comfyui": {
                "status": "not_needed",
                "message": "Demo mode uses the bundled clip mock. ComfyUI is not contacted.",
            },
        },
    }


def test_demo_mode_never_contacts_comfyui() -> None:
    def fail_if_called() -> Check:
        raise AssertionError("ComfyUI must not be probed in demo mode")

    settings = Settings(database_url=DATABASE_URL, provider_mode="demo")
    checks = HealthChecks(database=ok, storage=ok, comfyui=fail_if_called)

    response = TestClient(create_app(settings, checks=checks)).get("/api/v1/health")

    assert response.json()["checks"]["comfyui"]["status"] == "not_needed"


def test_health_outside_demo_mode_reports_comfyui_reachability() -> None:
    online = make_client(provider_mode="subscription").get("/api/v1/health").json()
    offline_check = Check(status=CheckStatus.OFFLINE, message="ComfyUI is not running.")
    offline = make_client(provider_mode="subscription", comfyui=offline_check).get("/api/v1/health")

    assert online["demo_mode"] is False
    assert online["provider_mode"] == "subscription"
    assert online["checks"]["comfyui"] == {"status": "ok", "message": None}
    # ComfyUI being offline never makes the API unhealthy: everything else stays usable.
    assert offline.status_code == 200
    assert offline.json()["status"] == "ok"
    assert offline.json()["checks"]["comfyui"] == {
        "status": "offline",
        "message": "ComfyUI is not running.",
    }


def test_health_is_503_when_the_database_is_down() -> None:
    down = Check(status=CheckStatus.ERROR, message="The database is not reachable.")

    response = make_client(database=down).get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] == {
        "status": "error",
        "message": "The database is not reachable.",
    }
    assert body["checks"]["storage"]["status"] == "ok"


def test_health_is_503_when_storage_is_not_writable() -> None:
    broken = Check(status=CheckStatus.ERROR, message="The data folder is not writable.")

    response = make_client(storage=broken).get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["checks"]["storage"]["status"] == "error"


def test_a_crashing_check_is_reported_not_raised() -> None:
    def crash() -> Check:
        raise RuntimeError(f"cannot connect to {DATABASE_URL}")

    settings = Settings(database_url=DATABASE_URL)
    checks = HealthChecks(database=crash, storage=ok, comfyui=ok)

    response = TestClient(create_app(settings, checks=checks)).get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == {
        "status": "error",
        "message": "The check itself failed. See the API log.",
    }


def test_nfr01_health_never_returns_secrets() -> None:
    def crash() -> Check:
        raise RuntimeError(f"cannot connect to {DATABASE_URL}")

    settings = Settings(database_url=DATABASE_URL)
    checks = HealthChecks(database=crash, storage=ok, comfyui=ok)

    text = TestClient(create_app(settings, checks=checks)).get("/api/v1/health").text

    assert "super-secret-password" not in text
    assert "postgresql" not in text


def test_unversioned_paths_are_not_served() -> None:
    assert make_client().get("/health").status_code == 404
