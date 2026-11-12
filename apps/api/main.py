"""FastAPI application for Video Factory Studio.

Everything is served under /api/v1 (design doc section 10). `create_app` is a factory:
run it with `python -m apps.api`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.errors import COMMON_ERROR_RESPONSES, install_error_handlers
from apps.api.health import HealthChecks, default_checks
from apps.api.health import router as health_router
from apps.api.providers import DatabaseProviderService, ProviderService
from apps.api.providers import router as providers_router
from apps.api.settings import DatabaseSettingStore, SettingStore
from apps.api.settings import router as settings_router
from packages.adapters.limit_probe import ProviderProbe
from packages.adapters.storage import LocalStorage
from packages.core.db.session import make_engine, make_session_factory
from packages.core.settings import Settings, load_settings

API_PREFIX = "/api/v1"
API_VERSION = "0.1.0"


def create_app(
    settings: Settings | None = None,
    *,
    checks: HealthChecks | None = None,
    setting_store: SettingStore | None = None,
    provider_service: ProviderService | None = None,
) -> FastAPI:
    """Build the application.

    Without arguments the settings come from the environment. Tests pass their own
    settings, health checks, setting store and provider service, so no database or
    network is touched.
    """
    settings = settings if settings is not None else load_settings()
    given = (checks, setting_store, provider_service)
    engine = make_engine(settings.database_url) if None in given else None
    if engine is not None:
        sessions = make_session_factory(engine)
        checks = checks or default_checks(settings, engine, LocalStorage(settings.data_dir))
        setting_store = setting_store or DatabaseSettingStore(sessions)
        provider_service = provider_service or DatabaseProviderService(
            sessions, settings.provider_mode, ProviderProbe(settings)
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="Video Factory Studio API",
        version=API_VERSION,
        description="Local API for the Video Factory Studio interface.",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
        responses=COMMON_ERROR_RESPONSES,
        # Operation ids are the route function names, so the generated client reads well
        # (getHealth, not getHealthApiV1HealthGet). Route function names must be unique.
        generate_unique_id_function=lambda route: route.name,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.health_checks = checks
    app.state.setting_store = setting_store
    app.state.provider_service = provider_service
    install_error_handlers(app)
    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(settings_router, prefix=API_PREFIX)
    app.include_router(providers_router, prefix=API_PREFIX)
    return app
