"""The Postgres-backed job queue (design doc sections 4.3 and 4.4, decision D8).

Integration tests: they need a real Postgres because the guarantees come from row locks.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import PurePosixPath

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from packages.core import queue
from packages.core.db import models
from packages.core.enums import ErrorClass, JobStatus, JobTag

integration = pytest.mark.integration


# --- pure helpers: no database ---------------------------------------------------------


def test_input_hash_ignores_key_order_and_depends_on_type() -> None:
    first = queue.input_hash("render.scene", {"scene": "s01", "seed": 7})
    second = queue.input_hash("render.scene", {"seed": 7, "scene": "s01"})

    assert first == second
    assert len(first) == 64
    assert first != queue.input_hash("render.join", {"scene": "s01", "seed": 7})
    assert first != queue.input_hash("render.scene", {"scene": "s02", "seed": 7})


def test_output_path_is_derived_from_the_input_hash() -> None:
    digest = queue.input_hash("gen.image", {"asset": "a_hill_dawn"})

    path = queue.job_output_path("gen.image", digest)

    assert path == PurePosixPath("jobs") / "gen.image" / digest[:2] / digest
    # Same input, same path: a retry overwrites the same files (section 4.3).
    assert path == queue.job_output_path(
        "gen.image", queue.input_hash("gen.image", {"asset": "a_hill_dawn"})
    )


def test_backoff_schedule_matches_the_design() -> None:
    assert queue.MAX_ATTEMPTS == 3
    assert queue.BACKOFF_S == (10, 60, 300)
    assert queue.HEARTBEAT_INTERVAL_S == 10
    assert queue.STALE_AFTER_S == 60


# --- database helpers ------------------------------------------------------------------


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


def add_job(
    sessions: sessionmaker[Session],
    *,
    tag: JobTag = JobTag.CPU,
    job_type: str = "noop",
    payload: dict[str, object] | None = None,
    run_after: datetime | None = None,
) -> uuid.UUID:
    with sessions.begin() as session:
        return queue.enqueue(
            session, job_type=job_type, tag=tag, payload=payload, run_after=run_after
        ).id


def claim(sessions: sessionmaker[Session], tag: JobTag = JobTag.CPU) -> queue.ClaimedJob | None:
    with sessions.begin() as session:
        return queue.claim_next(session, tag)


def must_claim(sessions: sessionmaker[Session], tag: JobTag = JobTag.CPU) -> queue.ClaimedJob:
    claimed = claim(sessions, tag)
    assert claimed is not None
    return claimed


def load(sessions: sessionmaker[Session], job_id: uuid.UUID) -> models.Job:
    with sessions() as session:
        job = session.get(models.Job, job_id)
        assert job is not None
        return job


def seconds_until_due(sessions: sessionmaker[Session], job_id: uuid.UUID) -> float:
    with sessions() as session:
        value = session.execute(
            text("SELECT extract(epoch FROM run_after - now()) FROM job WHERE id = :id"),
            {"id": job_id},
        ).scalar_one()
        return float(value)


def make_stale(sessions: sessionmaker[Session], job_id: uuid.UUID, seconds: int = 120) -> None:
    with sessions.begin() as session:
        session.execute(
            text("UPDATE job SET heartbeat_at = now() - make_interval(secs => :s) WHERE id = :id"),
            {"s": seconds, "id": job_id},
        )


# --- enqueue and claim -----------------------------------------------------------------


@integration
def test_enqueue_stores_a_queued_job_with_its_input_hash(sessions: sessionmaker[Session]) -> None:
    job_id = add_job(sessions, payload={"scene": "s01"})

    job = load(sessions, job_id)
    assert job.status is JobStatus.QUEUED
    assert job.tag is JobTag.CPU
    assert job.attempts == 0
    assert job.input == {"scene": "s01"}
    assert job.input_hash == queue.input_hash("noop", {"scene": "s01"})


@integration
def test_claim_marks_the_job_running_with_a_heartbeat(sessions: sessionmaker[Session]) -> None:
    job_id = add_job(sessions)

    claimed = must_claim(sessions)

    assert claimed.id == job_id
    assert claimed.type == "noop"
    job = load(sessions, job_id)
    assert job.status is JobStatus.RUNNING
    assert job.started_at == claimed.started_at
    assert job.heartbeat_at is not None
    assert claim(sessions) is None


@integration
def test_claim_takes_the_oldest_due_job_of_the_requested_tag(
    sessions: sessionmaker[Session],
) -> None:
    later = datetime.now(UTC) + timedelta(hours=1)
    add_job(sessions, run_after=later)
    gpu_job = add_job(sessions, tag=JobTag.GPU)
    first = add_job(sessions, payload={"n": 1})
    second = add_job(sessions, payload={"n": 2})

    assert must_claim(sessions).id == first
    assert must_claim(sessions).id == second
    assert claim(sessions) is None, "a job scheduled for later must not be claimed"
    assert must_claim(sessions, JobTag.GPU).id == gpu_job


@integration
def test_d8_two_workers_never_run_the_same_job(sessions: sessionmaker[Session]) -> None:
    job_ids = {add_job(sessions, payload={"n": n}) for n in range(40)}
    start = threading.Barrier(8)

    def drain() -> list[uuid.UUID]:
        start.wait(timeout=10)
        taken: list[uuid.UUID] = []
        while (claimed := claim(sessions)) is not None:
            taken.append(claimed.id)
        return taken

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [future.result(timeout=60) for future in [pool.submit(drain) for _ in range(8)]]

    claimed_ids = [job_id for taken in results for job_id in taken]
    assert len(claimed_ids) == 40, "every job is claimed"
    assert len(set(claimed_ids)) == 40, "no job is claimed twice"
    assert set(claimed_ids) == job_ids


@integration
def test_d8_at_most_one_gpu_job_runs_at_a_time(sessions: sessionmaker[Session]) -> None:
    first = add_job(sessions, tag=JobTag.GPU, payload={"clip": 1})
    second = add_job(sessions, tag=JobTag.GPU, payload={"clip": 2})

    running = must_claim(sessions, JobTag.GPU)
    assert running.id == first
    assert claim(sessions, JobTag.GPU) is None, "a second gpu job must wait"
    assert claim(sessions, JobTag.CPU) is None

    with sessions.begin() as session:
        assert queue.complete(session, running, {"ok": True})
    assert must_claim(sessions, JobTag.GPU).id == second


@integration
def test_d8_simultaneous_gpu_claims_start_only_one_job(sessions: sessionmaker[Session]) -> None:
    for n in range(5):
        add_job(sessions, tag=JobTag.GPU, payload={"clip": n})
    start = threading.Barrier(8)

    def try_claim() -> queue.ClaimedJob | None:
        start.wait(timeout=10)
        return claim(sessions, JobTag.GPU)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [
            future.result(timeout=60) for future in [pool.submit(try_claim) for _ in range(8)]
        ]

    assert len([claimed for claimed in results if claimed is not None]) == 1
    with sessions() as session:
        running = session.execute(
            text("SELECT count(*) FROM job WHERE tag = 'gpu' AND status = 'running'")
        ).scalar_one()
    assert running == 1


# --- finishing a job -------------------------------------------------------------------


@integration
def test_complete_stores_output_and_cost(sessions: sessionmaker[Session]) -> None:
    job_id = add_job(sessions)
    claimed = must_claim(sessions)

    with sessions.begin() as session:
        assert queue.complete(session, claimed, {"frames": 90}, cost_usd=Decimal("0.0125"))

    job = load(sessions, job_id)
    assert job.status is JobStatus.SUCCEEDED
    assert job.output == {"frames": 90}
    assert job.cost_usd == Decimal("0.0125")
    assert job.finished_at is not None
    assert job.error_class is None


@integration
def test_retryable_failures_back_off_then_fail_after_three_attempts(
    sessions: sessionmaker[Session],
) -> None:
    job_id = add_job(sessions)

    for attempt, wait in ((1, 10), (2, 60)):
        claimed = must_claim(sessions)
        with sessions.begin() as session:
            outcome = queue.fail(session, claimed, ErrorClass.RETRYABLE, "ComfyUI busy")
        assert outcome is JobStatus.QUEUED
        job = load(sessions, job_id)
        assert job.attempts == attempt
        assert job.error_class is ErrorClass.RETRYABLE
        assert wait - 2 <= seconds_until_due(sessions, job_id) <= wait
        assert claim(sessions) is None, "the job waits for its backoff"
        with sessions.begin() as session:
            session.execute(text("UPDATE job SET run_after = now()"))

    claimed = must_claim(sessions)
    with sessions.begin() as session:
        outcome = queue.fail(session, claimed, ErrorClass.RETRYABLE, "ComfyUI busy")

    assert outcome is JobStatus.FAILED
    job = load(sessions, job_id)
    assert job.status is JobStatus.FAILED
    assert job.attempts == 3
    assert job.error_message == "ComfyUI busy"
    assert job.finished_at is not None


@integration
@pytest.mark.parametrize(
    "error_class", [ErrorClass.NEEDS_OWNER, ErrorClass.BUG, ErrorClass.INVALID_OUTPUT]
)
def test_other_error_classes_fail_immediately_without_retry(
    sessions: sessionmaker[Session], error_class: ErrorClass
) -> None:
    job_id = add_job(sessions)
    claimed = must_claim(sessions)

    with sessions.begin() as session:
        outcome = queue.fail(session, claimed, error_class, "Start ComfyUI")

    assert outcome is JobStatus.FAILED
    job = load(sessions, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error_class is error_class
    assert job.error_message == "Start ComfyUI"
    assert claim(sessions) is None


@integration
def test_plan_limit_waits_for_the_reset_time_without_using_an_attempt(
    sessions: sessionmaker[Session],
) -> None:
    job_id = add_job(sessions)
    claimed = must_claim(sessions)
    reset = datetime.now(UTC) + timedelta(hours=2)

    with sessions.begin() as session:
        outcome = queue.fail(
            session, claimed, ErrorClass.PLAN_LIMIT, "Plan limit reached", retry_at=reset
        )

    assert outcome is JobStatus.QUEUED
    job = load(sessions, job_id)
    assert job.attempts == 0
    assert job.error_class is ErrorClass.PLAN_LIMIT
    assert abs((job.run_after - reset).total_seconds()) < 1
    assert claim(sessions) is None


# --- heartbeat and restart recovery ----------------------------------------------------


@integration
def test_heartbeat_moves_the_timestamp_forward(sessions: sessionmaker[Session]) -> None:
    job_id = add_job(sessions)
    claimed = must_claim(sessions)
    make_stale(sessions, job_id, seconds=30)
    before = load(sessions, job_id).heartbeat_at

    with sessions.begin() as session:
        assert queue.heartbeat(session, claimed)

    after = load(sessions, job_id).heartbeat_at
    assert before is not None
    assert after is not None
    assert after > before


@integration
def test_fr18_a_job_with_a_stale_heartbeat_is_picked_up_again(
    sessions: sessionmaker[Session],
) -> None:
    stale_id = add_job(sessions, payload={"n": 1})
    fresh_id = add_job(sessions, payload={"n": 2})
    first_claim = must_claim(sessions)
    must_claim(sessions)
    make_stale(sessions, stale_id, seconds=61)

    with sessions.begin() as session:
        returned = queue.requeue_stale(session)

    assert returned == [stale_id]
    stale = load(sessions, stale_id)
    assert stale.status is JobStatus.QUEUED
    assert stale.attempts == 1
    assert stale.started_at is None
    assert load(sessions, fresh_id).status is JobStatus.RUNNING, "a live job is left alone"

    second_claim = must_claim(sessions)
    assert second_claim.id == stale_id
    assert second_claim.started_at != first_claim.started_at


@integration
def test_fr18_a_job_abandoned_three_times_fails_with_a_clear_message(
    sessions: sessionmaker[Session],
) -> None:
    job_id = add_job(sessions)

    for _ in range(3):
        must_claim(sessions)
        make_stale(sessions, job_id)
        with sessions.begin() as session:
            queue.requeue_stale(session)

    job = load(sessions, job_id)
    assert job.status is JobStatus.FAILED
    assert job.attempts == 3
    assert job.error_class is ErrorClass.RETRYABLE
    assert job.error_message is not None
    assert "stopped responding" in job.error_message


@integration
def test_a_late_result_from_a_replaced_worker_is_ignored(sessions: sessionmaker[Session]) -> None:
    job_id = add_job(sessions)
    old_claim = must_claim(sessions)
    make_stale(sessions, job_id)
    with sessions.begin() as session:
        queue.requeue_stale(session)
    new_claim = must_claim(sessions)

    with sessions.begin() as session:
        assert queue.complete(session, old_claim, {"from": "old worker"}) is False
        assert queue.heartbeat(session, old_claim) is False
        assert queue.fail(session, old_claim, ErrorClass.BUG, "late failure") is None

    assert load(sessions, job_id).status is JobStatus.RUNNING
    with sessions.begin() as session:
        assert queue.complete(session, new_claim, {"from": "new worker"})
    assert load(sessions, job_id).output == {"from": "new worker"}


# --- cancel ----------------------------------------------------------------------------


@integration
def test_cancel_stops_a_queued_job_and_discards_a_running_result(
    sessions: sessionmaker[Session],
) -> None:
    queued_id = add_job(sessions, payload={"n": 1})
    with sessions.begin() as session:
        assert queue.cancel(session, queued_id)
    assert load(sessions, queued_id).status is JobStatus.CANCELLED
    assert claim(sessions) is None

    running_id = add_job(sessions, payload={"n": 2})
    claimed = must_claim(sessions)
    with sessions.begin() as session:
        assert queue.cancel(session, running_id)
        assert queue.complete(session, claimed, {"ok": True}) is False
    assert load(sessions, running_id).status is JobStatus.CANCELLED

    with sessions.begin() as session:
        assert queue.cancel(session, running_id) is False, "a finished job cannot be cancelled"
