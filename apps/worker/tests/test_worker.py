"""The worker process: cpu and gpu loops, heartbeats and restart recovery (FR-18, D8)."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers import HANDLERS
from apps.worker.runner import Handler, JobContext, Worker
from packages.adapters.storage import LocalStorage
from packages.core import queue, removal
from packages.core.db import models
from packages.core.enums import ErrorClass, JobStatus, JobTag

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@contextmanager
def running_worker(
    sessions: sessionmaker[Session],
    handlers: dict[str, Handler],
    *,
    cpu_workers: int = 2,
    heartbeat_file: Path | None = None,
    stale_after_s: float = queue.STALE_AFTER_S,
    critic_enabled: bool = True,
    **options: Any,
) -> Iterator[Worker]:
    worker = Worker(
        sessions,
        handlers,
        critic_enabled=critic_enabled,
        cpu_workers=cpu_workers,
        poll_interval_s=0.02,
        maintenance_interval_s=0.05,
        stale_after_s=stale_after_s,
        heartbeat_file=heartbeat_file,
        **options,
    )
    stop = threading.Event()
    thread = threading.Thread(target=worker.run, args=(stop,))
    thread.start()
    try:
        yield worker
    finally:
        stop.set()
        thread.join(timeout=10)
        assert not thread.is_alive(), "the worker must stop when asked"


def add_job(
    sessions: sessionmaker[Session],
    job_type: str,
    tag: JobTag = JobTag.CPU,
    payload: dict[str, object] | None = None,
) -> uuid.UUID:
    with sessions.begin() as session:
        return queue.enqueue(session, job_type=job_type, tag=tag, payload=payload).id


def wait_for(
    sessions: sessionmaker[Session],
    job_id: uuid.UUID,
    done: Callable[[models.Job], bool],
    timeout_s: float = 10,
) -> models.Job:
    deadline = time.monotonic() + timeout_s
    while True:
        with sessions() as session:
            job = session.get(models.Job, job_id)
            assert job is not None
            if done(job):
                return job
        if time.monotonic() > deadline:
            pytest.fail(f"job {job_id} did not reach the expected state, it is {job.status}")
        time.sleep(0.02)


def finished(job: models.Job) -> bool:
    return job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}


def test_a_noop_job_completes(sessions: sessionmaker[Session]) -> None:
    job_id = add_job(sessions, "noop", payload={"hello": "world"})

    with running_worker(sessions, HANDLERS):
        job = wait_for(sessions, job_id, finished)

    assert job.status is JobStatus.SUCCEEDED
    assert job.output == {
        "echo": {"hello": "world"},
        "output_path": str(queue.job_output_path("noop", job.input_hash or "")),
    }
    assert job.finished_at is not None


def test_handler_error_classes_reach_the_job(sessions: sessionmaker[Session]) -> None:
    def needs_owner(_context: JobContext) -> None:
        raise queue.NeedsOwnerError("Start ComfyUI")

    def crashes(_context: JobContext) -> None:
        raise ZeroDivisionError("division by zero")

    owner_id = add_job(sessions, "needs_owner")
    bug_id = add_job(sessions, "crashes")
    unknown_id = add_job(sessions, "no_such_type")

    with running_worker(sessions, {"needs_owner": needs_owner, "crashes": crashes}):
        owner_job = wait_for(sessions, owner_id, finished)
        bug_job = wait_for(sessions, bug_id, finished)
        unknown_job = wait_for(sessions, unknown_id, finished)

    assert (owner_job.status, owner_job.error_class) == (JobStatus.FAILED, ErrorClass.NEEDS_OWNER)
    assert owner_job.error_message == "Start ComfyUI"
    assert (bug_job.status, bug_job.error_class) == (JobStatus.FAILED, ErrorClass.BUG)
    assert bug_job.error_message == "ZeroDivisionError: division by zero"
    assert (unknown_job.status, unknown_job.error_class) == (JobStatus.FAILED, ErrorClass.BUG)
    assert unknown_job.error_message == "No handler is registered for job type 'no_such_type'."


def test_a_retryable_error_returns_the_job_to_the_queue(sessions: sessionmaker[Session]) -> None:
    def busy(_context: JobContext) -> None:
        raise queue.RetryableError("ComfyUI busy")

    job_id = add_job(sessions, "busy")

    with running_worker(sessions, {"busy": busy}):
        job = wait_for(sessions, job_id, lambda job: job.attempts == 1)

    assert job.status is JobStatus.QUEUED
    assert job.error_class is ErrorClass.RETRYABLE


def test_fr18_a_job_left_running_by_a_dead_worker_is_resumed(
    sessions: sessionmaker[Session],
) -> None:
    job_id = add_job(sessions, "noop")
    with sessions.begin() as session:
        abandoned = queue.claim_next(session, JobTag.CPU)
        assert abandoned is not None
        session.execute(text("UPDATE job SET heartbeat_at = now() - interval '2 minutes'"))

    with running_worker(sessions, HANDLERS):
        job = wait_for(sessions, job_id, finished)

    assert job.status is JobStatus.SUCCEEDED
    assert job.attempts == 1, "the abandoned attempt is counted"


def test_fr18_long_jobs_keep_their_heartbeat_and_are_not_requeued(
    sessions: sessionmaker[Session],
) -> None:
    release = threading.Event()

    def slow(_context: JobContext) -> None:
        release.wait(timeout=10)

    job_id = add_job(sessions, "slow")

    # A job is stale after 0.3 s here, and the handler runs longer than that.
    with running_worker(sessions, {"slow": slow}, stale_after_s=0.3):
        wait_for(sessions, job_id, lambda job: job.status is JobStatus.RUNNING)
        time.sleep(0.8)
        still_running = wait_for(sessions, job_id, lambda _job: True)
        release.set()
        job = wait_for(sessions, job_id, finished)

    assert still_running.status is JobStatus.RUNNING
    assert still_running.attempts == 0
    assert job.status is JobStatus.SUCCEEDED


class Gauge:
    """Counts how many handlers run at the same moment."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def handler(self, _context: JobContext) -> None:
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        time.sleep(0.15)
        with self._lock:
            self.current -= 1


def test_d8_gpu_jobs_run_one_at_a_time(sessions: sessionmaker[Session]) -> None:
    gauge = Gauge()
    job_ids = [add_job(sessions, "clip", JobTag.GPU, {"n": n}) for n in range(3)]

    with running_worker(sessions, {"clip": gauge.handler}, cpu_workers=4):
        for job_id in job_ids:
            assert wait_for(sessions, job_id, finished).status is JobStatus.SUCCEEDED

    assert gauge.peak == 1


def test_cpu_jobs_run_with_the_configured_concurrency(sessions: sessionmaker[Session]) -> None:
    gauge = Gauge()
    job_ids = [add_job(sessions, "frame", JobTag.CPU, {"n": n}) for n in range(6)]

    with running_worker(sessions, {"frame": gauge.handler}, cpu_workers=2):
        for job_id in job_ids:
            assert wait_for(sessions, job_id, finished).status is JobStatus.SUCCEEDED

    assert gauge.peak == 2


def test_the_worker_touches_its_process_heartbeat_file(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    heartbeat = tmp_path / "nested" / "heartbeat"

    with running_worker(sessions, HANDLERS, heartbeat_file=heartbeat):
        deadline = time.monotonic() + 5
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(0.02)

    assert heartbeat.exists()


# --- deleting a video (Director mode design, "Deleting videos") ----------------------------


def _episode(sessions: sessionmaker[Session]) -> uuid.UUID:
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="plain")
        session.add(channel)
        session.flush()
        made = models.Episode(channel_id=channel.id, idea="A keeper who climbs a hill.")
        session.add(made)
        session.flush()
        return made.id


def _gone(sessions: sessionmaker[Session], episode_id: uuid.UUID, timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        with sessions() as session:
            if session.get(models.Episode, episode_id) is None:
                return
        if time.monotonic() > deadline:
            pytest.fail("the deleted episode was not removed")
        time.sleep(0.02)


def test_a_job_that_ends_after_its_video_was_deleted_is_thrown_away(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    storage = LocalStorage(tmp_path / "data")
    episode_id = _episode(sessions)
    started, release = threading.Event(), threading.Event()

    def slow(context: JobContext) -> dict[str, object]:
        storage.write_bytes(context.output_path / "picture.png", b"made while deleting")
        started.set()
        assert release.wait(timeout=10)
        return {"made": True}

    with sessions.begin() as session:
        queue.enqueue(session, job_type="slow", tag=JobTag.CPU, episode_id=episode_id)

    with running_worker(sessions, {"slow": slow}, storage=storage):
        assert started.wait(timeout=10)
        with sessions.begin() as session:
            assert removal.mark_deleted(session, episode_id) is True
            assert removal.purge(session, storage, episode_id) is False
        release.set()
        _gone(sessions, episode_id)

    with sessions() as session:
        assert session.scalars(select(models.Job)).all() == []
    assert not (tmp_path / "data" / "episodes" / str(episode_id)).exists()


def test_a_job_of_a_deleted_video_is_not_started(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    storage = LocalStorage(tmp_path / "data")
    episode_id = _episode(sessions)
    ran = threading.Event()
    with sessions.begin() as session:
        queue.enqueue(session, job_type="slow", tag=JobTag.CPU, episode_id=episode_id)
        # As after a worker that died: the video is marked, its job is still queued.
        session.execute(
            text("UPDATE episode SET deleted_at = now() WHERE id = :id"), {"id": episode_id}
        )

    with running_worker(sessions, {"slow": lambda _context: ran.set()}, storage=storage):
        _gone(sessions, episode_id)

    assert not ran.is_set()
