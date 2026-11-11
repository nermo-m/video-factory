"""Helpers for running Alembic from code and tests."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def alembic_config(database_url: str | None = None) -> Config:
    """Alembic configuration for this repository.

    Pass a database URL to target a specific database (tests do). Without one, the
    migration environment reads DATABASE_URL.
    """
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config
