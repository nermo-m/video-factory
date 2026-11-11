"""Shared pytest fixtures.

Integration tests need a real Postgres. Each test gets its own throwaway database, created
on the server named by TEST_DATABASE_URL (or by the POSTGRES_* values in .env).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

from packages.core.db.migrate import alembic_config


def _server_url() -> URL:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return make_url(explicit)
    password = os.environ.get("POSTGRES_PASSWORD")
    if password:
        return URL.create(
            "postgresql+psycopg",
            username=os.environ.get("POSTGRES_USER", "vfs"),
            password=password,
            host="127.0.0.1",
            port=int(os.environ.get("DB_HOST_PORT", "5433")),
            database=os.environ.get("POSTGRES_DB", "vfs"),
        )
    pytest.fail(
        "Integration tests need a Postgres server. Run `make test-integration`, or set "
        "TEST_DATABASE_URL to a server where the user may create databases.",
        pytrace=False,
    )


CONNECT_TIMEOUT_S = 5


@pytest.fixture(scope="session")
def postgres_server_url() -> URL:
    """The Postgres server for integration tests. Stops the run at once when it is down."""
    url = _server_url()
    probe = create_engine(url, connect_args={"connect_timeout": CONNECT_TIMEOUT_S})
    try:
        with probe.connect():
            pass
    except OperationalError:
        pytest.exit(
            f"Postgres does not answer at {url.host}:{url.port}. "
            "Start it with `docker compose up --detach --wait db` or run `make test-integration`.",
            returncode=1,
        )
    finally:
        probe.dispose()
    return url


@pytest.fixture
def database_url(postgres_server_url: URL) -> Iterator[str]:
    """URL of a fresh, empty database that is dropped after the test."""
    name = f"vfs_test_{uuid.uuid4().hex}"
    admin = create_engine(postgres_server_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        # The name is generated above from hex digits only, never from input.
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield postgres_server_url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def config(database_url: str) -> Config:
    """Alembic configuration aimed at the test database."""
    return alembic_config(database_url)


@pytest.fixture
def migrated(config: Config, engine: Engine) -> Engine:
    """An engine on a test database with every migration applied."""
    command.upgrade(config, "head")
    return engine
