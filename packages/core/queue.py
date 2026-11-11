"""Postgres-backed job queue (design doc sections 4.3 and 4.4, decision D8).

Rules this module enforces:

* Claiming uses SELECT ... FOR UPDATE SKIP LOCKED filtered by tag, so two workers never
  get the same job.
* At most one gpu job runs at a time. Gpu claims are serialised with an advisory lock and
  refused while any gpu job is running.
* `attempts` counts attempts that ended badly. A retryable failure or an abandoned job adds
  one. The job is retried with a backoff until MAX_ATTEMPTS is reached, then it fails.
* A running job is owned by one claim. Its `started_at` is the claim token: a worker that
  was presumed dead and replaced cannot overwrite the new owner's result.
* Every comparison of time uses the database clock, so containers need not agree on time.

Functions take a Session and never commit. The caller owns the transaction.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from packages.core.db.models import Job
from packages.core.enums import ErrorClass, JobStatus, JobTag

MAX_ATTEMPTS = 3
BACKOFF_S = (10, 60, 300)
HEARTBEAT_INTERVAL_S = 10
STALE_AFTER_S = 60
# How long a job waits when a plan limit gave no reset time (section 3.5: probe every 10 min).
PLAN_LIMIT_RETRY_S = 600

# Advisory lock key that serialises gpu claims ("VFS" + 1).
_GPU_CLAIM_LOCK = 0x56465301

ABANDONED_MESSAGE = "The worker stopped responding while running this job."


@dataclass(frozen=True)
class ClaimedJob:
    """A job this worker owns until it completes, fails or is presumed dead."""

    id: uuid.UUID
    type: str
    tag: JobTag
    input: dict[str, Any]
    input_hash: str
    attempts: int
    episode_id: uuid.UUID | None
    started_at: datetime


class JobError(Exception):
    """Raised by a job handler to fail the job with a specific error class."""

    def __init__(
        self, message: str, *, error_class: ErrorClass, retry_at: datetime | None = None
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.retry_at = retry_at


class RetryableError(JobError):
    """Timeout, rate limit, busy tool: retried automatically with backoff."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_class=ErrorClass.RETRYABLE)


class InvalidOutputError(JobError):
    """Model output failed validation, after the single corrective retry inside the skill."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_class=ErrorClass.INVALID_OUTPUT)


class NeedsOwnerError(JobError):
    """Only the owner can fix this. The message must say what to do."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_class=ErrorClass.NEEDS_OWNER)


class PlanLimitError(JobError):
    """A subscription plan limit was reached. The job waits, it is never sent to a paid API."""

    def __init__(self, message: str, *, retry_at: datetime | None = None) -> None:
        super().__init__(message, error_class=ErrorClass.PLAN_LIMIT, retry_at=retry_at)


def input_hash(job_type: str, payload: Mapping[str, Any]) -> str:
    """Stable SHA-256 of a job's type and input, independent of key order."""
    canonical = json.dumps(
        {"type": job_type, "input": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def job_output_path(job_type: str, digest: str) -> PurePosixPath:
    """Where a job writes its files, relative to the storage root.

    The path comes from the input hash, so a retry overwrites the same files.
    """
    return PurePosixPath("jobs") / job_type / digest[:2] / digest


def _in_seconds(seconds: float) -> ColumnElement[datetime]:
    return func.now() + func.make_interval(0, 0, 0, 0, 0, 0, seconds)


def enqueue(
    session: Session,
    *,
    job_type: str,
    tag: JobTag,
    payload: Mapping[str, Any] | None = None,
    episode_id: uuid.UUID | None = None,
    run_after: datetime | None = None,
) -> Job:
    """Add a queued job. It becomes claimable once the caller commits."""
    data = dict(payload or {})
    job = Job(
        episode_id=episode_id,
        type=job_type,
        tag=tag,
        status=JobStatus.QUEUED,
        input=data,
        input_hash=input_hash(job_type, data),
    )
    if run_after is not None:
        job.run_after = run_after
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session, tag: JobTag) -> ClaimedJob | None:
    """Claim the oldest due job with this tag, or return None when there is nothing to do."""
    if tag is JobTag.GPU:
        session.execute(select(func.pg_advisory_xact_lock(_GPU_CLAIM_LOCK)))
        gpu_busy = session.execute(
            select(Job.id).where(Job.tag == JobTag.GPU, Job.status == JobStatus.RUNNING).limit(1)
        ).first()
        if gpu_busy is not None:
            return None

    job = session.execute(
        select(Job)
        .where(Job.status == JobStatus.QUEUED, Job.tag == tag, Job.run_after <= func.now())
        .order_by(Job.run_after, Job.created_at, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return None

    # clock_timestamp() differs for every claim, which makes started_at a usable claim token.
    job.status = JobStatus.RUNNING
    job.started_at = func.clock_timestamp()
    job.heartbeat_at = func.now()
    job.finished_at = None
    session.flush()
    session.refresh(job)
    assert job.started_at is not None  # noqa: S101 - set two lines above, narrows the type
    return ClaimedJob(
        id=job.id,
        type=job.type,
        tag=job.tag,
        input=dict(job.input),
        input_hash=job.input_hash or input_hash(job.type, job.input),
        attempts=job.attempts,
        episode_id=job.episode_id,
        started_at=job.started_at,
    )


def _owned(session: Session, claim: ClaimedJob) -> Job | None:
    """The claimed job, locked, if this claim still owns it."""
    return session.execute(
        select(Job)
        .where(
            Job.id == claim.id,
            Job.status == JobStatus.RUNNING,
            Job.started_at == claim.started_at,
        )
        .with_for_update()
    ).scalar_one_or_none()


def heartbeat(session: Session, claim: ClaimedJob) -> bool:
    """Tell the queue this job is still being worked on. False when the claim was lost."""
    job = _owned(session, claim)
    if job is None:
        return False
    job.heartbeat_at = func.now()
    return True


def complete(
    session: Session,
    claim: ClaimedJob,
    output: Mapping[str, Any] | None = None,
    *,
    cost_usd: Decimal = Decimal("0"),
) -> bool:
    """Mark the job succeeded. False when the claim was lost, and nothing is written."""
    job = _owned(session, claim)
    if job is None:
        return False
    job.status = JobStatus.SUCCEEDED
    job.output = dict(output or {})
    job.cost_usd = cost_usd
    job.error_class = None
    job.error_message = None
    job.finished_at = func.now()
    return True


def _end_attempt_badly(job: Job, message: str, *, delay_s: float) -> JobStatus:
    """Count a bad attempt, then requeue the job or fail it for good."""
    job.attempts += 1
    job.error_class = ErrorClass.RETRYABLE
    job.error_message = message
    job.heartbeat_at = None
    if job.attempts >= MAX_ATTEMPTS:
        job.status = JobStatus.FAILED
        job.finished_at = func.now()
        return JobStatus.FAILED
    job.status = JobStatus.QUEUED
    job.started_at = None
    job.run_after = _in_seconds(delay_s)
    return JobStatus.QUEUED


def fail(
    session: Session,
    claim: ClaimedJob,
    error_class: ErrorClass,
    message: str,
    *,
    retry_at: datetime | None = None,
) -> JobStatus | None:
    """Record a failed attempt. Returns the job's new status, or None when the claim was lost."""
    job = _owned(session, claim)
    if job is None:
        return None

    if error_class is ErrorClass.RETRYABLE:
        delay = BACKOFF_S[min(job.attempts, len(BACKOFF_S) - 1)]
        return _end_attempt_badly(job, message, delay_s=delay)

    job.error_class = error_class
    job.error_message = message
    job.heartbeat_at = None
    if error_class is ErrorClass.PLAN_LIMIT:
        # Waiting for a plan to reset is not a failed attempt.
        job.status = JobStatus.QUEUED
        job.started_at = None
        job.run_after = retry_at if retry_at is not None else _in_seconds(PLAN_LIMIT_RETRY_S)
        return JobStatus.QUEUED

    job.status = JobStatus.FAILED
    job.finished_at = func.now()
    return JobStatus.FAILED


def requeue_stale(session: Session, *, stale_after_s: float = STALE_AFTER_S) -> list[uuid.UUID]:
    """Return running jobs whose worker went quiet to the queue. Returns their ids."""
    stale = (
        session.execute(
            select(Job)
            .where(
                Job.status == JobStatus.RUNNING,
                Job.heartbeat_at < func.now() - func.make_interval(0, 0, 0, 0, 0, 0, stale_after_s),
            )
            .order_by(Job.created_at, Job.id)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    for job in stale:
        _end_attempt_badly(job, ABANDONED_MESSAGE, delay_s=0)
    return [job.id for job in stale]


def cancel(session: Session, job_id: uuid.UUID) -> bool:
    """Cancel a queued or running job. A running handler's later result is discarded."""
    job = session.execute(
        select(Job)
        .where(Job.id == job_id, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        .with_for_update()
    ).scalar_one_or_none()
    if job is None:
        return False
    job.status = JobStatus.CANCELLED
    job.heartbeat_at = None
    job.finished_at = func.now()
    return True
