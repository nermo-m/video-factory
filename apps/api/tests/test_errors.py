"""Every error uses one shape (design doc section 10):

{"error": {"code": "...", "message": "...", "details": {}}}
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from apps.api.errors import ApiError
from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import API_PREFIX, create_app
from packages.core.settings import Settings

SECRET = "super-secret-password"  # noqa: S105 - a fake value that must never leak


class Idea(BaseModel):
    idea: str = Field(min_length=3)
    target_duration_s: int


def make_app() -> FastAPI:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    settings = Settings(database_url=f"postgresql+psycopg://vfs:{SECRET}@db:5432/vfs")
    app = create_app(settings, checks=HealthChecks(database=ok, storage=ok, comfyui=ok))

    @app.post(f"{API_PREFIX}/test/ideas")
    def create_idea(idea: Idea) -> Idea:
        return idea

    @app.get(f"{API_PREFIX}/test/conflict")
    def conflict() -> None:
        raise ApiError(
            409,
            "gate_not_open",
            "This episode is not waiting for approval.",
            details={"state": "render"},
        )

    @app.get(f"{API_PREFIX}/test/crash")
    def crash() -> None:
        raise RuntimeError(f"connection to postgresql://vfs:{SECRET}@db failed")

    return app


def client() -> TestClient:
    return TestClient(make_app(), raise_server_exceptions=False)


def assert_error_shape(body: dict[str, object]) -> dict[str, object]:
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "details"}
    assert isinstance(error["code"], str)
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], dict)
    return error


def test_unknown_route_uses_the_error_shape() -> None:
    response = client().get("/api/v1/nothing-here")

    assert response.status_code == 404
    error = assert_error_shape(response.json())
    assert error["code"] == "not_found"


def test_wrong_method_uses_the_error_shape() -> None:
    response = client().delete("/api/v1/health")

    assert response.status_code == 405
    assert assert_error_shape(response.json())["code"] == "method_not_allowed"


def test_validation_errors_name_the_fields() -> None:
    response = client().post("/api/v1/test/ideas", json={"idea": "x"})

    assert response.status_code == 422
    error = assert_error_shape(response.json())
    assert error["code"] == "validation_error"
    assert error["message"] == "The request is not valid. Check the listed fields."
    details = error["details"]
    assert isinstance(details, dict)
    fields = {problem["field"] for problem in details["fields"]}
    assert fields == {"body.idea", "body.target_duration_s"}
    assert all(problem["message"] for problem in details["fields"])


def test_malformed_json_is_a_validation_error() -> None:
    response = client().post(
        "/api/v1/test/ideas", content="{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert assert_error_shape(response.json())["code"] == "validation_error"


def test_api_errors_carry_code_message_and_details() -> None:
    response = client().get("/api/v1/test/conflict")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "gate_not_open",
            "message": "This episode is not waiting for approval.",
            "details": {"state": "render"},
        }
    }


def test_nfr01_unhandled_errors_are_generic_and_leak_nothing() -> None:
    response = client().get("/api/v1/test/crash")

    assert response.status_code == 500
    error = assert_error_shape(response.json())
    assert error["code"] == "internal_error"
    assert error["message"] == "Something went wrong on the server. The error was logged."
    assert SECRET not in response.text
    assert "RuntimeError" not in response.text
    assert "postgresql" not in response.text
