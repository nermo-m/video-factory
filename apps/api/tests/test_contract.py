"""Contract tests (design doc section 14.1): the committed OpenAPI file is what the app
produces, every error response is documented with the common shape, and the API answers
the way its own OpenAPI document says it will."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import schemathesis
from fastapi import FastAPI

from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.openapi import OPENAPI_PATH, render_openapi
from apps.api.providers import MemoryProviderService
from apps.api.settings import MemorySettingStore
from packages.core.settings import Settings

ROOT = Path(__file__).resolve().parents[3]


def make_app() -> FastAPI:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    settings = Settings(database_url="postgresql+psycopg://vfs:not-used@db:5432/vfs")
    return create_app(
        settings,
        checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
        setting_store=MemorySettingStore(),
        provider_service=MemoryProviderService(),
    )


def test_committed_openapi_file_is_current() -> None:
    committed = OPENAPI_PATH.read_text(encoding="utf-8")

    assert committed == render_openapi(), (
        "apps/api/openapi.json is out of date. Run: make generate-api"
    )


def test_openapi_file_is_where_the_web_client_reads_it() -> None:
    assert OPENAPI_PATH == ROOT / "apps" / "api" / "openapi.json"
    config = (ROOT / "apps" / "web" / "openapi-ts.config.ts").read_text(encoding="utf-8")
    assert "../api/openapi.json" in config


def test_every_documented_error_uses_the_common_error_shape() -> None:
    document = json.loads(render_openapi())

    error_refs = set()
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            for status, response in operation["responses"].items():
                if status == "200" or (path.endswith("/health") and status == "503"):
                    continue
                schema = response["content"]["application/json"]["schema"]
                error_refs.add((path, method, status, schema.get("$ref")))

    assert error_refs, "operations must document their error responses"
    assert {ref for *_, ref in error_refs} == {"#/components/schemas/ErrorResponse"}
    assert "HTTPValidationError" not in document["components"]["schemas"]


schema = schemathesis.openapi.from_asgi("/api/v1/openapi.json", make_app())


@schema.parametrize()
def test_api_matches_its_openapi_document(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate()
