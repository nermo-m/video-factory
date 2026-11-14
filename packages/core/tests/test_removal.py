"""Deleting a video, on a real Postgres (Director mode design, "Deleting videos")."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from packages.adapters.storage import LocalStorage
from packages.core import assets, queue, removal, usage
from packages.core.db import models
from packages.core.enums import (
    AssetKind,
    AssetOrigin,
    JobStatus,
    JobTag,
    Provider,
    RenderKind,
    SpecAuthor,
    SpecKind,
)
from packages.core.storage import StorageError

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "data")


def episode(sessions: sessionmaker[Session], channel_id: uuid.UUID | None = None) -> models.Episode:
    with sessions.begin() as session:
        if channel_id is None:
            channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="plain")
            session.add(channel)
            session.flush()
            channel_id = channel.id
        made = models.Episode(channel_id=channel_id, idea="A keeper who climbs a hill.")
        session.add(made)
        session.flush()
        return made


def count(sessions: sessionmaker[Session], model: type[Any]) -> int:
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def filled(
    sessions: sessionmaker[Session], storage: LocalStorage, made: models.Episode
) -> dict[str, str]:
    """Give the episode one of everything a video collects. Returns the files written."""
    files = {
        "picture": f"episodes/{made.id}/jobs/gen.image/ab/abcd/a_harbour.png",
        "upload": f"uploads/{made.id}/a_photo.png",
        "scene": f"episodes/{made.id}/scenes/s01.mp4",
        "video": f"episodes/{made.id}/jobs/render.join/cd/cdef/video.mp4",
    }
    for path in files.values():
        storage.write_bytes(path, b"file")
    with sessions.begin() as session:
        assets.ensure_library(session, storage, made.channel_id)
        own = session.get(models.Episode, made.id)
        assert own is not None
        first = models.SpecVersion(
            episode_id=made.id,
            version=1,
            kind=SpecKind.AUTHORED,
            author=SpecAuthor.MODEL,
            body={"scenes": []},
        )
        session.add(first)
        session.flush()
        second = models.SpecVersion(
            episode_id=made.id,
            version=2,
            kind=SpecKind.RESOLVED,
            author=SpecAuthor.MODEL,
            body={"scenes": []},
            parent_id=first.id,
        )
        session.add(second)
        session.flush()
        own.current_spec_id = first.id
        for key, path in (("a_harbour", files["picture"]), ("a_photo", files["upload"])):
            asset = models.Asset(
                channel_id=made.channel_id,
                episode_id=made.id,
                key=assets.episode_key(made.id, key),
                kind=AssetKind.IMAGE,
                origin=AssetOrigin.GENERATED,
            )
            session.add(asset)
            session.flush()
            assets.add_version(session, asset, file_path=path)
        session.add(
            models.Render(
                episode_id=made.id,
                resolved_spec_id=second.id,
                kind=RenderKind.DRAFT,
                file_path=files["video"],
            )
        )
        done = queue.enqueue(
            session, job_type="plan.shotlist", tag=JobTag.CPU, payload={}, episode_id=made.id
        )
        done.status = JobStatus.SUCCEEDED
        usage.record_model_call(
            session,
            provider=Provider.DEMO,
            model="recorded",
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal("0"),
            latency_ms=1,
            skill="shotlist",
            skill_version="1.0",
            input_hash="0" * 64,
            job_id=done.id,
        )
    return files


def test_mark_deleted_cancels_queued_jobs_and_hides_the_episode(
    sessions: sessionmaker[Session],
) -> None:
    made = episode(sessions)
    with sessions.begin() as session:
        queued = queue.enqueue(
            session, job_type="gen.image", tag=JobTag.CPU, payload={}, episode_id=made.id
        )

    with sessions.begin() as session:
        assert removal.mark_deleted(session, made.id) is True

    with sessions() as session:
        stored = session.get(models.Episode, made.id)
        job = session.get(models.Job, queued.id)
    assert stored is not None
    assert stored.deleted_at is not None
    assert job is not None
    assert job.status is JobStatus.CANCELLED


def test_mark_deleted_twice_is_the_same_as_once(sessions: sessionmaker[Session]) -> None:
    made = episode(sessions)
    with sessions.begin() as session:
        removal.mark_deleted(session, made.id)
    with sessions() as session:
        first = session.get(models.Episode, made.id)
        assert first is not None
        at = first.deleted_at

    with sessions.begin() as session:
        assert removal.mark_deleted(session, made.id) is True

    with sessions() as session:
        again = session.get(models.Episode, made.id)
    assert again is not None
    assert again.deleted_at == at


def test_mark_deleted_of_an_unknown_id_returns_false(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        assert removal.mark_deleted(session, uuid.uuid4()) is False


def test_purge_removes_rows_and_files_but_keeps_library_pictures_and_usage(
    sessions: sessionmaker[Session], storage: LocalStorage, tmp_path: Path
) -> None:
    made = episode(sessions)
    other = episode(sessions, made.channel_id)
    files = filled(sessions, storage, made)
    kept = filled(sessions, storage, other)
    calls_before = count(sessions, models.ModelCall)

    with sessions.begin() as session:
        removal.mark_deleted(session, made.id)
        assert removal.purge(session, storage, made.id) is True

    with sessions() as session:
        assert session.get(models.Episode, made.id) is None
        for model in (models.SpecVersion, models.Job, models.Render, models.Asset):
            left = session.scalars(select(model).where(model.episode_id == made.id)).all()
            assert left == [], model.__name__
        library = session.scalars(
            select(models.Asset).where(models.Asset.episode_id.is_(None))
        ).all()
        orphans = session.scalar(
            select(func.count())
            .select_from(models.AssetVersion)
            .outerjoin(models.Asset, models.Asset.id == models.AssetVersion.asset_id)
            .where(models.Asset.id.is_(None))
        )
        calls = session.scalars(select(models.ModelCall)).all()
    assert len(library) == 4
    assert orphans == 0
    assert len(calls) == calls_before
    assert sum(call.job_id is None for call in calls) == 1
    for path in files.values():
        assert not storage.exists(path), path
    assert not (tmp_path / "data" / "episodes" / str(made.id)).exists()
    for path in kept.values():
        assert storage.exists(path), path
    assert (tmp_path / "data" / "library" / "a_hill_dawn" / "v1.png").is_file()
    assert count(sessions, models.Episode) == 1


def test_purge_waits_while_a_job_is_running(
    sessions: sessionmaker[Session], storage: LocalStorage
) -> None:
    made = episode(sessions)
    files = filled(sessions, storage, made)
    with sessions.begin() as session:
        queue.enqueue(session, job_type="gen.image", tag=JobTag.CPU, payload={}, episode_id=made.id)
    with sessions.begin() as session:
        assert queue.claim_next(session, JobTag.CPU) is not None

    with sessions.begin() as session:
        removal.mark_deleted(session, made.id)
        assert removal.purge(session, storage, made.id) is False

    with sessions() as session:
        assert session.get(models.Episode, made.id) is not None
    assert storage.exists(files["picture"])


def test_purge_of_an_episode_that_is_not_marked_does_nothing(
    sessions: sessionmaker[Session], storage: LocalStorage
) -> None:
    made = episode(sessions)

    with sessions.begin() as session:
        assert removal.purge(session, storage, made.id) is False

    with sessions() as session:
        assert session.get(models.Episode, made.id) is not None


def test_remove_tree_refuses_to_leave_the_data_folder(storage: LocalStorage) -> None:
    storage.write_bytes("episodes/one/file.bin", b"x")

    for bad in ("", ".", "..", "../outside", "/absolute"):
        with pytest.raises(StorageError):
            storage.remove_tree(bad)

    assert storage.exists("episodes/one/file.bin")


def test_remove_tree_of_a_folder_that_is_not_there_is_fine(storage: LocalStorage) -> None:
    storage.remove_tree("episodes/nothing-here")
