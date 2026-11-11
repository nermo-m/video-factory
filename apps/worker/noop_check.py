"""Smoke check: enqueue a no-op job and wait until the worker has run it.

    python -m apps.worker.noop_check

Exit code 0 when the job succeeded, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence

from packages.core import queue
from packages.core.db.models import Job
from packages.core.db.session import make_engine, make_session_factory
from packages.core.enums import JobStatus, JobTag
from packages.core.settings import SettingsError, load_settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one no-op job through the queue")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except SettingsError as error:
        sys.stderr.write(f"{error}\n")
        return 1

    engine = make_engine(settings.database_url)
    sessions = make_session_factory(engine)
    try:
        with sessions.begin() as session:
            job_id = queue.enqueue(
                session, job_type="noop", tag=JobTag.CPU, payload={"sent_at": time.time()}
            ).id
        sys.stdout.write(f"no-op job {job_id} queued\n")

        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            with sessions() as session:
                job = session.get(Job, job_id)
                status = job.status if job is not None else None
            if status is JobStatus.SUCCEEDED:
                sys.stdout.write(f"no-op job {job_id} succeeded\n")
                return 0
            if status in {JobStatus.FAILED, JobStatus.CANCELLED}:
                sys.stderr.write(f"no-op job {job_id} ended as {status}\n")
                return 1
            time.sleep(0.5)
        sys.stderr.write(f"no-op job {job_id} did not finish in {args.timeout:g} s\n")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
