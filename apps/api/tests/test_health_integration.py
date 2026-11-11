"""GET /health with the real probes: a real Postgres and a real folder."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from apps.api.health import default_checks
from apps.api.main import create_app
from packages.adapters.storage import LocalStorage
from packages.core.settings import Settings

pytestmark = pytest.mark.integration


def test_health_is_ok_with_a_real_database_and_data_folder(
    engine: Engine, database_url: str, tmp_path: Path
) -> None:
    settings = Settings(database_url=database_url, data_dir=str(tmp_path))
    checks = default_checks(settings, engine, LocalStorage(tmp_path))

    response = TestClient(create_app(settings, checks=checks)).get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == {"status": "ok", "message": None}
    assert body["checks"]["storage"] == {"status": "ok", "message": None}


def test_health_is_503_when_the_database_does_not_answer(tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    url = f"postgresql+psycopg://vfs:wrong@127.0.0.1:{closed_port}/vfs?connect_timeout=2"
    dead_engine = create_engine(url)
    settings = Settings(database_url=url, data_dir=str(tmp_path))
    checks = default_checks(settings, dead_engine, LocalStorage(tmp_path))

    response = TestClient(create_app(settings, checks=checks)).get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == {
        "status": "error",
        "message": "The database is not reachable.",
    }
    assert "wrong" not in response.text


def test_health_is_503_when_the_data_folder_is_missing(
    engine: Engine, database_url: str, tmp_path: Path
) -> None:
    missing = tmp_path / "not-mounted"
    settings = Settings(database_url=database_url, data_dir=str(missing))
    checks = default_checks(settings, engine, LocalStorage(missing))

    response = TestClient(create_app(settings, checks=checks)).get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["checks"]["storage"] == {
        "status": "error",
        "message": "The data folder does not exist.",
    }
