"""GET /health: liveness, database, storage, ComfyUI reachability and the demo mode flag
(design doc section 10).

The API is healthy when the database and the storage work. ComfyUI is reported but never
makes the API unhealthy: everything that does not need the GPU stays usable.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from packages.adapters.clip.probe import comfyui_reachable
from packages.core.settings import Settings
from packages.core.storage import StorageAdapter, StorageError

logger = logging.getLogger("apps.api")

COMFYUI_CACHE_S = 10.0


class CheckStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    OFFLINE = "offline"
    NOT_NEEDED = "not_needed"


class Check(BaseModel):
    status: CheckStatus
    message: str | None = Field(default=None, description="What is wrong and what to do.")


class HealthStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


class HealthCheckResults(BaseModel):
    database: Check
    storage: Check
    comfyui: Check


class HealthResponse(BaseModel):
    status: HealthStatus
    provider_mode: Literal["demo", "subscription", "api"]
    demo_mode: bool = Field(description="True when PROVIDER_MODE is demo.")
    checks: HealthCheckResults


@dataclass(frozen=True)
class HealthChecks:
    """The three probes behind /health. Tests replace them with plain functions."""

    database: Callable[[], Check]
    storage: Callable[[], Check]
    comfyui: Callable[[], Check]


def default_checks(settings: Settings, engine: Engine, storage: StorageAdapter) -> HealthChecks:
    def database() -> Check:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return Check(status=CheckStatus.ERROR, message="The database is not reachable.")
        return Check(status=CheckStatus.OK)

    def check_storage() -> Check:
        try:
            storage.check()
        except StorageError as error:
            return Check(status=CheckStatus.ERROR, message=str(error))
        return Check(status=CheckStatus.OK)

    lock = threading.Lock()
    cached: dict[str, tuple[float, Check]] = {}

    def comfyui() -> Check:
        # The interface polls /health every 2 seconds. Probing the host that often would be
        # wasteful, so the answer is reused for a few seconds.
        with lock:
            hit = cached.get("comfyui")
            if hit is not None and time.monotonic() - hit[0] < COMFYUI_CACHE_S:
                return hit[1]
        if comfyui_reachable(settings.comfyui_url):
            result = Check(status=CheckStatus.OK)
        else:
            result = Check(
                status=CheckStatus.OFFLINE,
                message="ComfyUI is not running. Start ComfyUI on the host to generate clips.",
            )
        with lock:
            cached["comfyui"] = (time.monotonic(), result)
        return result

    return HealthChecks(database=database, storage=check_storage, comfyui=comfyui)


def _run(name: str, check: Callable[[], Check]) -> Check:
    try:
        return check()
    except Exception:
        # A probe must never take /health down with it, and its error text may hold
        # connection details, so only the log gets it.
        logger.exception("health check crashed", extra={"check": name})
        return Check(status=CheckStatus.ERROR, message="The check itself failed. See the API log.")


def run_health(settings: Settings, checks: HealthChecks) -> HealthResponse:
    demo_mode = settings.provider_mode == "demo"
    database = _run("database", checks.database)
    storage = _run("storage", checks.storage)
    if demo_mode:
        comfyui = Check(
            status=CheckStatus.NOT_NEEDED,
            message="Demo mode uses the bundled clip mock. ComfyUI is not contacted.",
        )
    else:
        comfyui = _run("comfyui", checks.comfyui)

    healthy = database.status is CheckStatus.OK and storage.status is CheckStatus.OK
    return HealthResponse(
        status=HealthStatus.OK if healthy else HealthStatus.UNAVAILABLE,
        provider_mode=settings.provider_mode,  # type: ignore[arg-type]  # validated in settings
        demo_mode=demo_mode,
        checks=HealthCheckResults(database=database, storage=storage, comfyui=comfyui),
    )


router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database or storage is down."}},
    summary="Liveness, database, storage, ComfyUI reachability and demo mode",
)
def get_health(request: Request, response: Response) -> HealthResponse:
    settings: Settings = request.app.state.settings
    checks: HealthChecks = request.app.state.health_checks
    report = run_health(settings, checks)
    if report.status is not HealthStatus.OK:
        response.status_code = 503
    return report
