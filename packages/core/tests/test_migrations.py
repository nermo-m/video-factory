"""Integration tests for the Alembic baseline on a real Postgres (design doc section 14.1).

Each test gets its own throwaway database, so no test depends on another's data.
Run with: make test-integration
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.core import enums
from packages.core.db import Base, models
from packages.core.tests.test_models import SECTION_9_TABLES

pytestmark = pytest.mark.integration


def table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_migration_applies_and_rolls_back_cleanly(config: Config, engine: Engine) -> None:
    command.upgrade(config, "head")
    assert table_names(engine) == SECTION_9_TABLES | {"alembic_version"}

    command.downgrade(config, "base")
    assert table_names(engine) == {"alembic_version"}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 0

    command.upgrade(config, "head")
    assert table_names(engine) == SECTION_9_TABLES | {"alembic_version"}


def test_models_and_migration_agree(migrated: Engine) -> None:
    with migrated.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)

    assert diff == [], f"autogenerate found differences: {diff}"


def test_section9_listed_indexes_exist_in_the_database(migrated: Engine) -> None:
    inspector = inspect(migrated)

    def indexes(table: str) -> dict[tuple[str | None, ...], bool]:
        return {
            tuple(index["column_names"]): bool(index["unique"])
            for index in inspector.get_indexes(table)
        }

    def uniques(table: str) -> set[tuple[str, ...]]:
        return {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table)
        }

    assert ("status", "tag", "run_after") in indexes("job")
    assert ("state",) in indexes("episode")
    assert ("channel_id", "key") in uniques("asset")
    assert ("episode_id", "version") in uniques("spec_version")


def make_channel() -> models.Channel:
    return models.Channel(
        name="Night Scrolls",
        motto="Small steps still count.",
        style_block="night village, paper scrolls, ink",
        voice_id="bm_george",
        theme="night_scrolls",
    )


def make_episode(session: Session) -> models.Episode:
    channel = make_channel()
    session.add(channel)
    session.flush()
    episode = models.Episode(channel_id=channel.id, idea="A keeper climbs the same hill.")
    session.add(episode)
    session.flush()
    return episode


def test_server_fills_id_timestamps_and_defaults(migrated: Engine) -> None:
    with Session(migrated) as session:
        episode = make_episode(session)
        session.commit()
        session.refresh(episode)

        assert isinstance(episode.id, uuid.UUID)
        assert episode.created_at.tzinfo is not None
        assert episode.updated_at >= episode.created_at
        assert episode.state is enums.EpisodeState.IDEA
        assert episode.awaiting_approval is False
        assert episode.total_cost_usd == Decimal("0")

    with migrated.begin() as connection:
        # A raw insert without id or timestamps must work too: the defaults live in the database.
        connection.execute(text("INSERT INTO setting (key, value) VALUES ('probe', '{}')"))
        row = connection.execute(text("SELECT id, created_at FROM setting")).one()
        assert row.id is not None
        assert row.created_at is not None


def test_updated_at_moves_when_a_row_changes(migrated: Engine) -> None:
    with Session(migrated) as session:
        episode = make_episode(session)
        session.commit()
        first = episode.updated_at

        episode.title = "The Lighthouse Keeper"
        session.commit()
        session.refresh(episode)

        assert episode.updated_at > first


def test_spec_version_numbers_are_unique_per_episode(migrated: Engine) -> None:
    with Session(migrated) as session:
        episode = make_episode(session)
        for _ in range(2):
            session.add(
                models.SpecVersion(
                    episode_id=episode.id,
                    version=1,
                    kind=enums.SpecKind.AUTHORED,
                    body={"spec_version": "2.0"},
                    author=enums.SpecAuthor.MODEL,
                )
            )
        with pytest.raises(IntegrityError, match="uq_spec_version_episode_id_version"):
            session.flush()


def test_asset_keys_are_unique_per_channel(migrated: Engine) -> None:
    with Session(migrated) as session:
        episode = make_episode(session)
        for _ in range(2):
            session.add(
                models.Asset(
                    channel_id=episode.channel_id,
                    episode_id=episode.id,
                    key="a_hill_dawn",
                    kind=enums.AssetKind.IMAGE,
                    origin=enums.AssetOrigin.GENERATED,
                )
            )
        with pytest.raises(IntegrityError, match="uq_asset_channel_id_key"):
            session.flush()


def test_only_one_asset_version_can_be_active(migrated: Engine) -> None:
    with Session(migrated) as session:
        episode = make_episode(session)
        asset = models.Asset(
            channel_id=episode.channel_id,
            key="a_hill_dawn",
            kind=enums.AssetKind.IMAGE,
            origin=enums.AssetOrigin.LIBRARY,
        )
        session.add(asset)
        session.flush()
        session.add(models.AssetVersion(asset_id=asset.id, file_path="a/v1.png", is_active=True))
        session.add(models.AssetVersion(asset_id=asset.id, file_path="a/v2.png", is_active=False))
        session.flush()

        session.add(models.AssetVersion(asset_id=asset.id, file_path="a/v3.png", is_active=True))
        with pytest.raises(IntegrityError, match="uq_asset_version_one_active"):
            session.flush()


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        ("UPDATE episode SET state = 'published'", "ck_episode_state_valid"),
        ("UPDATE episode SET total_cost_usd = -1", "ck_episode_total_cost_usd_not_negative"),
        (
            "INSERT INTO job (type, tag, status) VALUES ('noop', 'tpu', 'queued')",
            "ck_job_tag_valid",
        ),
        (
            "INSERT INTO job (type, tag, status) VALUES ('noop', 'cpu', 'paused')",
            "ck_job_status_valid",
        ),
        (
            "INSERT INTO job (type, tag, status, attempts) VALUES ('noop', 'cpu', 'queued', -1)",
            "ck_job_attempts_not_negative",
        ),
        (
            "INSERT INTO provider_status (provider, state, source) VALUES ('other', 'ok', 'app')",
            "ck_provider_status_provider_valid",
        ),
    ],
)
def test_check_constraints_reject_invalid_values(
    migrated: Engine, statement: str, constraint: str
) -> None:
    with Session(migrated) as session:
        make_episode(session)
        session.commit()

    with migrated.connect() as connection, pytest.raises(IntegrityError, match=constraint):
        connection.execute(text(statement))


def test_a_job_needs_no_episode(migrated: Engine) -> None:
    with Session(migrated) as session:
        job = models.Job(type="noop", tag=enums.JobTag.CPU)
        session.add(job)
        session.commit()
        session.refresh(job)

        assert job.episode_id is None
        assert job.status is enums.JobStatus.QUEUED
        assert job.attempts == 0
        assert job.run_after is not None


def test_rows_are_never_removed_by_cascade(migrated: Engine) -> None:
    with Session(migrated) as session:
        episode = make_episode(session)
        session.commit()
        channel_id = episode.channel_id

    with migrated.connect() as connection, pytest.raises(IntegrityError):
        connection.execute(text("DELETE FROM channel WHERE id = :id"), {"id": channel_id})
