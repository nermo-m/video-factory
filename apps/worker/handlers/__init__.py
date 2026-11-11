"""Job handlers by job type. A handler is a plain function that takes a JobContext."""

from __future__ import annotations

from apps.worker.handlers.noop import noop
from apps.worker.runner import Handler

HANDLERS: dict[str, Handler] = {
    "noop": noop,
}
