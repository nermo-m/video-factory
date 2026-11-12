"""GET and PUT /settings (design doc sections 3.4 and 10).

Non-secret settings only. The one setting so far is the owner's "Use paid APIs" switch.
The provider mode is shown but cannot be changed here: it comes from the environment at
start-up and never changes by itself (FR-28). Secrets are reported as present or absent,
never by value (NFR-01).
"""

from __future__ import annotations

import os
from typing import Protocol

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session, sessionmaker

from apps.api.errors import BAD_BODY_RESPONSE
from packages.core import app_settings
from packages.core.providers import PaidApiRefusedError, ensure_paid_apis_allowed
from packages.core.settings import Settings

router = APIRouter(tags=["settings"])

# Reported as present or absent. Their values never leave the server.
SECRET_VARIABLES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


class SettingStore(Protocol):
    def paid_apis_confirmed(self) -> bool:
        """Whether the owner has switched "Use paid APIs" on."""

    def set_paid_apis_confirmed(self, confirmed: bool) -> None:
        """Store the switch."""


class DatabaseSettingStore:
    """The switch in the `setting` table, where the worker reads it too."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def paid_apis_confirmed(self) -> bool:
        with self._sessions() as session:
            return app_settings.paid_apis_confirmed(session)

    def set_paid_apis_confirmed(self, confirmed: bool) -> None:
        with self._sessions.begin() as session:
            app_settings.set_paid_apis_confirmed(session, confirmed)


class MemorySettingStore:
    """Keeps the switch in memory. For tests and for writing the OpenAPI document."""

    def __init__(self, confirmed: bool = False) -> None:
        self._confirmed = confirmed

    def paid_apis_confirmed(self) -> bool:
        return self._confirmed

    def set_paid_apis_confirmed(self, confirmed: bool) -> None:
        self._confirmed = confirmed


class SettingsResponse(BaseModel):
    provider_mode: str = Field(
        description="demo, subscription or api. Set by PROVIDER_MODE at start-up, read-only."
    )
    use_paid_apis: bool = Field(description='The owner\'s "Use paid APIs" switch.')
    paid_apis_active: bool = Field(
        description="True only when the mode is api and the switch is on."
    )
    paid_apis_message: str | None = Field(
        description="Why paid APIs are off, in plain words. Null when they are on."
    )
    secrets: dict[str, bool] = Field(
        description="Which secret environment variables are set. Never their values."
    )


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_paid_apis: StrictBool


def _answer(settings: Settings, store: SettingStore) -> SettingsResponse:
    confirmed = store.paid_apis_confirmed()
    try:
        ensure_paid_apis_allowed(settings.provider_mode, confirmed=confirmed)
        refusal = None
    except PaidApiRefusedError as refused:
        refusal = str(refused)
    return SettingsResponse(
        provider_mode=settings.provider_mode,
        use_paid_apis=confirmed,
        paid_apis_active=refusal is None,
        paid_apis_message=refusal,
        secrets={name: bool(os.environ.get(name, "").strip()) for name in SECRET_VARIABLES},
    )


@router.get("/settings", summary="Non-secret settings and which secrets are present")
def get_settings(request: Request) -> SettingsResponse:
    return _answer(request.app.state.settings, request.app.state.setting_store)


@router.put(
    "/settings",
    summary='Turn the "Use paid APIs" switch on or off',
    responses=BAD_BODY_RESPONSE,
)
def put_settings(update: SettingsUpdate, request: Request) -> SettingsResponse:
    store: SettingStore = request.app.state.setting_store
    store.set_paid_apis_confirmed(update.use_paid_apis)
    return _answer(request.app.state.settings, store)
