"""The API liveness route (design doc section 10: GET /health under /api/v1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_health_reports_ok_under_the_versioned_base_path() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unversioned_paths_are_not_served() -> None:
    client = TestClient(create_app())

    assert client.get("/health").status_code == 404
