"""Worker process for Video Factory Studio.

For now the process only proves it is alive by touching a heartbeat file, which the
container health check reads. The cpu and gpu job loops arrive with the job queue card.
"""

from __future__ import annotations

import logging
import os
import signal
import tempfile
import threading
from pathlib import Path
from types import FrameType

HEARTBEAT_INTERVAL_S = 5.0

logger = logging.getLogger("apps.worker")


def heartbeat_path() -> Path:
    """Where the heartbeat lives: WORKER_HEARTBEAT_FILE, or the system temp folder."""
    configured = os.environ.get("WORKER_HEARTBEAT_FILE")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "vfs-worker-heartbeat"


def run(
    stop: threading.Event, heartbeat: Path, *, interval_s: float = HEARTBEAT_INTERVAL_S
) -> None:
    """Touch the heartbeat file until asked to stop."""
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    while not stop.is_set():
        heartbeat.touch()
        stop.wait(interval_s)


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "info").upper())
    stop = threading.Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("signal %s received, stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    heartbeat = heartbeat_path()
    logger.info("worker started, heartbeat at %s", heartbeat)
    run(stop, heartbeat)
    logger.info("worker stopped")
    return 0
