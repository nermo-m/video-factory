"""The errors the bridge answers with.

`code` is the error class a caller acts on, `status` the HTTP status that goes with it.
The codes and what the worker does with them are listed in the README of this folder.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

BAD_REQUEST = "bad_request"
FORBIDDEN = "forbidden"
NOT_FOUND = "not_found"
METHOD_NOT_ALLOWED = "method_not_allowed"
PAYLOAD_TOO_LARGE = "payload_too_large"
UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
NOT_INSTALLED = "not_installed"
NOT_SIGNED_IN = "not_signed_in"
NOT_PLAN_SIGN_IN = "not_plan_sign_in"
BUSY = "busy"
TIMEOUT = "timeout"
PLAN_LIMIT = "plan_limit"
TOOL_FAILED = "tool_failed"
INVALID_OUTPUT = "invalid_output"
INTERNAL = "internal"


class BridgeError(Exception):
    """A request the bridge could not fulfil, with the reason in a form a program can read."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int,
        tool: str | None = None,
        retry_at: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.tool = tool
        self.retry_at = retry_at

    def to_json(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "tool": self.tool,
                "retry_at": self.retry_at.isoformat() if self.retry_at is not None else None,
            }
        }


def bad_request(message: str, *, status: int = 400) -> BridgeError:
    return BridgeError(BAD_REQUEST, message, status=status)


def brief(text: str, limit: int = 300) -> str:
    """A tool's own words, on one line and short enough for an error message."""
    joined = " ".join(text.split())
    return joined if len(joined) <= limit else joined[: limit - 1].rstrip() + "…"
