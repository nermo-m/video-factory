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

from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers import HANDLERS
from apps.worker.handlers.clips import clip_handlers
from apps.worker.handlers.pictures import picture_handlers
from apps.worker.handlers.plan import plan_handlers
from apps.worker.handlers.produce import cached_voice, produce_handlers
from apps.worker.handlers.shotlist import shotlist_handlers
from apps.worker.runner import Handler, Worker
from packages.adapters.factory import Adapters
from packages.adapters.limit_probe import ProviderProbe
from packages.adapters.llm.base import LLMAdapter
from packages.core import app_settings
from packages.core.db.session import make_engine, make_session_factory
from packages.core.logs import configure_logging
from packages.core.options import Writer
from packages.core.settings import Settings, SettingsError, load_settings
from packages.render.encode import join_clips

logger = logging.getLogger("apps.worker")


def heartbeat_path() -> Path:
    """Where the process heartbeat lives: WORKER_HEARTBEAT_FILE, or the system temp folder."""
    configured = os.environ.get("WORKER_HEARTBEAT_FILE")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "vfs-worker-heartbeat"


def build_handlers(settings: Settings, sessions: sessionmaker[Session]) -> dict[str, Handler]:
    """Every job type this worker can run."""

    def language_model(writer: Writer | None = None) -> LLMAdapter:
        """The model of the configured mode, with the owner's paid API switch as it is now.
        `writer` is the owner's choice of who writes a plan, when they made one."""
        with sessions() as session:
            confirmed = app_settings.paid_apis_confirmed(session)
        return Adapters(settings, paid_apis_confirmed=confirmed).llm(writer)

    local = Adapters(settings)
    return {
        **HANDLERS,
        **plan_handlers(sessions, language_model, local.storage()),
        **shotlist_handlers(sessions, language_model),
        **picture_handlers(sessions, storage=local.storage(), image=local.image),
        **clip_handlers(
            sessions,
            storage=local.storage(),
            data_dir=Path(settings.data_dir),
            clips=local.clip,
            join=join_clips,
        ),
        **produce_handlers(
            sessions,
            storage=local.storage(),
            data_dir=Path(settings.data_dir),
            tts=cached_voice(local.tts),
        ),
    }


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
    sessions = make_session_factory(engine)
    handlers = build_handlers(settings, sessions)
    worker = Worker(
        sessions,
        handlers,
        cpu_workers=settings.cpu_workers,
        heartbeat_file=heartbeat_path(),
        critic_enabled=settings.critic_enabled,
        provider_mode=settings.provider_mode,
        limit_probe=ProviderProbe(settings),
        limit_check_interval_s=settings.limit_check_minutes * 60,
        storage=Adapters(settings).storage(),
    )
    logger.info(
        "worker started",
        extra={
            "cpu_workers": settings.cpu_workers,
            "provider_mode": settings.provider_mode,
            "job_types": sorted(handlers),
        },
    )
    worker.run(stop)
    engine.dispose()
    logger.info("worker stopped")
    return 0
