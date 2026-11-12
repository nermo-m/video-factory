"""Worker process entry point: python -m apps.worker"""

from __future__ import annotations

import logging
import os
import signal
import sys
import tempfile
import threading
from pathlib import Path
from types import FrameType

from apps.worker.handlers import HANDLERS
from apps.worker.runner import Worker
from packages.core.db.session import make_engine, make_session_factory
from packages.core.logs import configure_logging
from packages.core.settings import SettingsError, load_settings

logger = logging.getLogger("apps.worker")


def heartbeat_path() -> Path:
    """Where the process heartbeat lives: WORKER_HEARTBEAT_FILE, or the system temp folder."""
    configured = os.environ.get("WORKER_HEARTBEAT_FILE")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "vfs-worker-heartbeat"


def main() -> int:
    try:
        settings = load_settings()
    except SettingsError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    configure_logging(settings.log_level)

    stop = threading.Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("signal received, stopping after the running jobs", extra={"signal": signum})
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    engine = make_engine(settings.database_url)
    worker = Worker(
        make_session_factory(engine),
        HANDLERS,
        cpu_workers=settings.cpu_workers,
        heartbeat_file=heartbeat_path(),
        critic_enabled=settings.critic_enabled,
    )
    logger.info(
        "worker started",
        extra={
            "cpu_workers": settings.cpu_workers,
            "provider_mode": settings.provider_mode,
            "job_types": sorted(HANDLERS),
        },
    )
    worker.run(stop)
    engine.dispose()
    logger.info("worker stopped")
    return 0
