"""The worker: one process, two kinds of loop (design doc section 3.1).

* cpu loop: `cpu_workers` threads, each claiming and running cpu jobs.
* gpu loop: one thread. The queue also refuses a second running gpu job (D8).
* maintenance loop: keeps heartbeats fresh, returns abandoned jobs to the queue and touches
  the process heartbeat file that the container health check reads.

A handler signals an expected failure by raising a JobError subclass. Anything else is a
bug: the stack trace is logged and the job fails without retry (section 4.4).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from packages.core import pipeline, queue
from packages.core.enums import ErrorClass, JobTag

logger = logging.getLogger("apps.worker")


@dataclass(frozen=True)
class JobContext:
    """What a handler receives."""

    job: queue.ClaimedJob
    # Folder for this job's files, relative to the storage root. It comes from the input
    # hash, so a retry writes to the same place.
    output_path: PurePosixPath


Handler = Callable[[JobContext], Mapping[str, Any] | None]


class Worker:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        handlers: Mapping[str, Handler],
        *,
        cpu_workers: int = 2,
        poll_interval_s: float = 1.0,
        maintenance_interval_s: float = queue.HEARTBEAT_INTERVAL_S,
        stale_after_s: float = queue.STALE_AFTER_S,
        heartbeat_file: Path | None = None,
        critic_enabled: bool = True,
    ) -> None:
        if cpu_workers < 1:
            raise ValueError("cpu_workers must be 1 or more")
        self._sessions = sessions
        self._handlers = dict(handlers)
        self._cpu_workers = cpu_workers
        self._poll_interval_s = poll_interval_s
        self._maintenance_interval_s = maintenance_interval_s
        self._stale_after_s = stale_after_s
        self._heartbeat_file = heartbeat_file
        self._critic_enabled = critic_enabled
        self._active: dict[int, queue.ClaimedJob] = {}
        self._active_lock = threading.Lock()

    def run(self, stop: threading.Event) -> None:
        """Run every loop until `stop` is set, then wait for running handlers to return."""
        threads = [
            threading.Thread(target=self._job_loop, args=(JobTag.CPU, stop), name=f"cpu-{n}")
            for n in range(self._cpu_workers)
        ]
        threads.append(threading.Thread(target=self._job_loop, args=(JobTag.GPU, stop), name="gpu"))
        threads.append(threading.Thread(target=self._maintenance_loop, args=(stop,), name="maint"))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    # --- job loops -----------------------------------------------------------------

    def _job_loop(self, tag: JobTag, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                with self._sessions.begin() as session:
                    claim = queue.claim_next(session, tag)
            except SQLAlchemyError:
                # The database may be restarting. Keep the loop alive and try again.
                logger.exception("could not claim a job, will retry", extra={"tag": tag.value})
                stop.wait(self._poll_interval_s)
                continue
            if claim is None:
                stop.wait(self._poll_interval_s)
                continue
            self._execute(claim)

    def _execute(self, claim: queue.ClaimedJob) -> None:
        ids = {"job_id": claim.id, "episode_id": claim.episode_id, "job_type": claim.type}
        thread_id = threading.get_ident()
        with self._active_lock:
            self._active[thread_id] = claim
        logger.info("job started", extra=ids)
        try:
            handler = self._handlers.get(claim.type)
            if handler is None:
                message = f"No handler is registered for job type '{claim.type}'."
                self._fail(claim, ErrorClass.BUG, message, ids)
                return
            context = JobContext(claim, queue.job_output_path(claim.type, claim.input_hash))
            output = handler(context)
        except queue.JobError as error:
            self._fail(claim, error.error_class, str(error), ids, retry_at=error.retry_at)
        except Exception as error:
            # Section 4.4, class "bug": log the stack trace, fail the job, do not retry.
            logger.exception("job crashed", extra=ids)
            self._fail(claim, ErrorClass.BUG, f"{type(error).__name__}: {error}", ids)
        else:
            self._complete(claim, output, ids)
        finally:
            with self._active_lock:
                self._active.pop(thread_id, None)

    def _complete(
        self, claim: queue.ClaimedJob, output: Mapping[str, Any] | None, ids: dict[str, Any]
    ) -> None:
        try:
            with self._sessions.begin() as session:
                kept = queue.complete(session, claim, output)
                if kept and claim.episode_id is not None:
                    self._move_episode_on(session, claim, ids)
        except SQLAlchemyError:
            # The job stays running, goes stale and is picked up again. Jobs are idempotent.
            logger.exception("could not store the job result", extra=ids)
            return
        if kept:
            logger.info("job succeeded", extra=ids)
        else:
            logger.warning("job result discarded: the job was cancelled or reassigned", extra=ids)

    def _move_episode_on(
        self, session: Session, claim: queue.ClaimedJob, ids: dict[str, Any]
    ) -> None:
        """Tell the pipeline about the result, in the transaction that stores it.

        When the pipeline cannot move on (for example, the next state needs a spec that is
        not there), that is rolled back by itself and the job keeps its result. The
        episode then waits until it is advanced by hand.
        """
        try:
            with session.begin_nested():
                pipeline.job_succeeded(session, claim.id, critic_enabled=self._critic_enabled)
        except pipeline.PipelineError as error:
            logger.warning(
                "the job succeeded but the episode could not move on: %s", error, extra=ids
            )

    def _fail(
        self,
        claim: queue.ClaimedJob,
        error_class: ErrorClass,
        message: str,
        ids: dict[str, Any],
        *,
        retry_at: datetime | None = None,
    ) -> None:
        try:
            with self._sessions.begin() as session:
                status = queue.fail(session, claim, error_class, message, retry_at=retry_at)
        except SQLAlchemyError:
            logger.exception("could not store the job failure", extra=ids)
            return
        logger.warning(
            "job attempt ended: %s",
            message,
            extra={
                **ids,
                "error_class": error_class.value,
                "status": status.value if status is not None else None,
            },
        )

    # --- maintenance ---------------------------------------------------------------

    def _maintenance_loop(self, stop: threading.Event) -> None:
        if self._heartbeat_file is not None:
            self._heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
        while not stop.is_set():
            try:
                self._maintain()
            except SQLAlchemyError:
                logger.exception("maintenance pass failed, will retry")
            # The process is alive even when the database is not: keep the file fresh so the
            # container is not restarted while it waits for the database to come back.
            if self._heartbeat_file is not None:
                self._heartbeat_file.touch()
            stop.wait(self._maintenance_interval_s)

    def _maintain(self) -> None:
        with self._active_lock:
            active = list(self._active.values())
        with self._sessions.begin() as session:
            for claim in active:
                queue.heartbeat(session, claim)
            returned = queue.requeue_stale(session, stale_after_s=self._stale_after_s)
        for job_id in returned:
            logger.warning("abandoned job returned to the queue", extra={"job_id": job_id})
