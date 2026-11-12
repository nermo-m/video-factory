"""/settings with the real store: the switch is kept in the `setting` table."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.settings import DatabaseSettingStore
from packages.core import app_settings
from packages.core.settings import Settings

pytestmark = pytest.mark.integration


def test_the_switch_set_through_the_api_is_what_the_worker_reads(
    migrated: Engine, database_url: str
) -> None:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    sessions = sessionmaker(migrated, expire_on_commit=False)
    settings = Settings(database_url=database_url, provider_mode="api")
    client = TestClient(
        create_app(
            settings,
            checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
            setting_store=DatabaseSettingStore(sessions),
        )
    )

    assert client.get("/api/v1/settings").json()["use_paid_apis"] is False
    with sessions() as session:
        assert app_settings.paid_apis_confirmed(session) is False

    assert client.put("/api/v1/settings", json={"use_paid_apis": True}).status_code == 200

    with sessions() as session:
        assert app_settings.paid_apis_confirmed(session) is True
    assert client.get("/api/v1/settings").json()["paid_apis_active"] is True
