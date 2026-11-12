"""One error shape for the whole API (design doc section 10):

    {"error": {"code": "...", "message": "...", "details": {}}}

Messages are written for the owner: what happened and what to do next. Internal detail
(exception text, connection strings, stack traces) goes to the log, never to the response.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("apps.api")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable reason, for example not_found.")
    message: str = Field(description="What happened and what to do next, in plain words.")
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    """Raise this from a route to answer with a specific status, code and message."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


_HTTP_CODES = {
    400: ("bad_request", "The request could not be understood."),
    401: ("unauthorized", "Sign in to continue."),
    403: ("forbidden", "This action is not allowed."),
    404: ("not_found", "Nothing exists at this address."),
    405: ("method_not_allowed", "This address does not support that action."),
}

#: Error responses every operation may return, for the OpenAPI document.
COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "The request is not valid."},
    500: {"model": ErrorResponse, "description": "Unexpected server error."},
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or {}))
    return JSONResponse(body.model_dump(), status_code=status_code, headers=headers)


#: For operations that take a body: a body that cannot be read at all, for example bytes
#: that are not text. A readable body with wrong fields is a 422.
BAD_BODY_RESPONSE: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "The request body could not be read."},
}


def _allowed_methods(request: Request) -> list[str]:
    """Every method the API documents for the requested address.

    Two routes can share an address (GET and PUT /settings). Starlette's own answer names
    only the methods of the first one it finds, so the list is taken from the OpenAPI
    document, which is what clients are told. Empty for an address that is not in it.
    """
    for template, operations in request.app.openapi()["paths"].items():
        pattern = re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(template))
        if re.fullmatch(pattern, request.url.path):
            return sorted(method.upper() for method in operations)
    return []


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            error.status_code, error.code, error.message, error.details, error.headers
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(error.status_code, ("http_error", "The request failed."))
        headers = dict(error.headers) if error.headers else None
        if error.status_code == 405 and (allowed := _allowed_methods(request)):
            kept = {
                name: value for name, value in (headers or {}).items() if name.lower() != "allow"
            }
            headers = {**kept, "allow": ", ".join(allowed)}
        return error_response(error.status_code, code, message, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {"field": ".".join(str(part) for part in problem["loc"]), "message": problem["msg"]}
            for problem in error.errors()
        ]
        return error_response(
            422,
            "validation_error",
            "The request is not valid. Check the listed fields.",
            {"fields": fields},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _error: Exception) -> JSONResponse:
        # The stack trace goes to the log. The response stays generic so no internal
        # detail or secret can leak (NFR-01).
        logger.exception(
            "unhandled error", extra={"method": request.method, "path": request.url.path}
        )
        return error_response(
            500, "internal_error", "Something went wrong on the server. The error was logged."
        )
