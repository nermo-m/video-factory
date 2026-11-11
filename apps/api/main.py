"""FastAPI application for Video Factory Studio.

Everything is served under /api/v1 (design doc section 10). This module holds the
application factory. Routes beyond liveness arrive with their own cards.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

API_PREFIX = "/api/v1"

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up and answering."""
    return {"status": "ok"}


def create_app() -> FastAPI:
    app = FastAPI(
        title="Video Factory Studio API",
        version="0.1.0",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
    )
    app.include_router(router, prefix=API_PREFIX)
    return app


app = create_app()
