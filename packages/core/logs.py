"""Structured JSON logs (NFR-03).

One JSON object per line with time, level, logger and message, plus any fields passed
through `extra`, such as job_id and episode_id. Fields whose names look like secrets are
replaced before they are written (NFR-01).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

LEVELS = ("debug", "info", "warning", "error")

_STANDARD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_SECRET_MARKERS = ("password", "secret", "token", "api_key", "apikey", "authorization", "cookie")
_SECRET_NAMES = frozenset({"database_url", "dsn"})
REDACTED = "[redacted]"


def _is_secret(name: str) -> bool:
    lowered = name.lower()
    return lowered in _SECRET_NAMES or any(marker in lowered for marker in _SECRET_MARKERS)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name, value in record.__dict__.items():
            if name in _STANDARD_FIELDS or name.startswith("_"):
                continue
            entry[name] = REDACTED if _is_secret(name) else value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: str = "info", *, stream: TextIO | None = None) -> None:
    """Send every log record to one JSON-lines stream (standard error by default)."""
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
