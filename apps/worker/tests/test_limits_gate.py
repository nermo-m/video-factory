"""The worker and the usage and limits tracker (section 3.5, FR-31, FR-32, FR-34).

"Before starting a job the worker checks provider_status. A limited or paused provider
keeps its jobs queued with a visible reason."
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.runner import JobContext
from apps.worker.tests.test_worker import running_worker
from packages.core import limits, queue
from packages.core.db import models
from packages.core.enums import ErrorClass, JobStatus, JobTag, Provider, ProviderState
from packages.core.queue import PlanLimitError

pytestmark = pytest.mark.integration

CLAUDE = Provider.CLAUDE_PLAN


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def episode_id(sessions: sessionmaker[Session]) -> uuid.UUID:
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="night_scrolls")
        session.add(channel)
        session.flush()
        episode = models.Episode(channel_id=channel.id, idea="A keeper who climbs a hill.")
        session.add(episode)
        session.flush()
        return episode.id


def add(sessions: sessionmaker[Session], job_type: str, episode_id: uuid.UUID | None) -> uuid.UUID:
    with sessions.begin() as session:
        job = queue.enqueue(session, job_type=job_type, tag=JobTag.CPU)
        job.episode_id = episode_id
        return job.id


def job(sessions: sessionmaker[Session], job_id: uuid.UUID) -> models.Job:
    with sessions() as session:
        found = session.get(models.Job, job_id)
        assert found is not None
        return found


def wait_for(condition: Callable[[], bool], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "the worker did not get there in time"
        time.sleep(0.02)


def pause_claude(sessions: sessionmaker[Session]) -> None:
    """Use up a budget of nothing, so the Claude plan is paused by budget."""
    with sessions.begin() as session:
        limits.set_budget(session, CLAUDE, {"calls_5h": 0, "calls_7d": 0})
        limits.record_usage(session, provider=CLAUDE, model="m")


class Counter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, context: JobContext) -> dict[str, Any]:
        self.calls += 1
        return {"done": True}


def test_fr32_a_job_of_a_paused_provider_stays_queued_with_the_reason(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    pause_claude(sessions)
    handler = Counter()
    job_id = add(sessions, "plan.brief", episode_id)

    with running_worker(sessions, {"plan.brief": handler}, provider_mode="subscription"):
        wait_for(lambda: job(sessions, job_id).error_message is not None)

    waiting = job(sessions, job_id)
    assert handler.calls == 0
    assert waiting.status is JobStatus.QUEUED
    assert waiting.error_class is ErrorClass.PLAN_LIMIT
    assert "budget for the Claude plan" in (waiting.error_message or "")
    assert waiting.attempts == 0, "waiting for a budget is not a failed attempt"
    assert waiting.run_after > datetime.now(UTC)


def test_fr32_continue_anyway_lets_the_episodes_job_run(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    pause_claude(sessions)
    handler = Counter()
    job_id = add(sessions, "plan.brief", episode_id)

    with running_worker(sessions, {"plan.brief": handler}, provider_mode="subscription"):
        wait_for(lambda: job(sessions, job_id).error_message is not None)
        with sessions.begin() as session:
            limits.allow_episode(session, CLAUDE, episode_id)
        wait_for(lambda: job(sessions, job_id).status is JobStatus.SUCCEEDED)

    assert handler.calls == 1


def test_a_job_that_needs_no_provider_runs_whatever_the_providers_do(
    sessions: sessionmaker[Session],
) -> None:
    pause_claude(sessions)
    handler = Counter()
    job_id = add(sessions, "render.scene", None)

    with running_worker(sessions, {"render.scene": handler}, provider_mode="subscription"):
        wait_for(lambda: job(sessions, job_id).status is JobStatus.SUCCEEDED)


def test_demo_mode_is_never_held_back(sessions: sessionmaker[Session]) -> None:
    pause_claude(sessions)
    handler = Counter()
    job_id = add(sessions, "plan.brief", None)

    with running_worker(sessions, {"plan.brief": handler}, provider_mode="demo"):
        wait_for(lambda: job(sessions, job_id).status is JobStatus.SUCCEEDED)


def test_fr31_a_limit_reported_by_a_tool_limits_the_provider_and_the_next_job_waits(
    sessions: sessionmaker[Session],
) -> None:
    until = datetime.now(UTC) + timedelta(hours=2)
    calls: list[str] = []

    def limited(context: JobContext) -> dict[str, Any]:
        calls.append(context.job.type)
        raise PlanLimitError("You've hit your session limit", retry_at=until)

    first = add(sessions, "plan.brief", None)

    with running_worker(
        sessions, {"plan.brief": limited, "plan.script": limited}, provider_mode="subscription"
    ):
        wait_for(lambda: job(sessions, first).error_message is not None)
        second = add(sessions, "plan.script", None)
        wait_for(lambda: job(sessions, second).error_message is not None)

    with sessions.begin() as session:
        status = limits.refresh(session, CLAUDE, now=datetime.now(UTC))
        assert status.state is ProviderState.LIMITED
        assert status.limited_until == until
        assert status.last_error == "You've hit your session limit"
    assert calls == ["plan.brief"], "the second job never reached the tool"
    waiting = job(sessions, second)
    assert waiting.status is JobStatus.QUEUED
    assert "usage limit" in (waiting.error_message or "")
    assert waiting.run_after == until


class Probe:
    def __init__(self) -> None:
        self.free: list[Provider] = []
        self.called: list[Provider] = []

    def free_check(self, provider: Provider) -> str | None:
        self.free.append(provider)
        return None

    def tiny_call(self, provider: Provider) -> None:
        self.called.append(provider)


def test_fr34_the_worker_checks_the_providers_by_itself_without_a_model_call(
    sessions: sessionmaker[Session],
) -> None:
    probe = Probe()

    with running_worker(
        sessions, {}, provider_mode="subscription", limit_probe=probe, limit_check_interval_s=0.1
    ):
        wait_for(lambda: len(probe.free) >= 4)

    assert set(probe.free) == {CLAUDE, Provider.CHATGPT_PLAN}
    assert probe.called == []
    with sessions.begin() as session:
        assert limits.refresh(session, CLAUDE, now=datetime.now(UTC)).last_checked_at is not None


def test_fr34_the_workers_check_lifts_a_limit_and_the_waiting_job_runs(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        limits.limit_reached(session, CLAUDE, message="limit", retry_at=None, now=datetime.now(UTC))
    probe, handler = Probe(), Counter()
    job_id = add(sessions, "plan.brief", None)

    with running_worker(
        sessions,
        {"plan.brief": handler},
        provider_mode="subscription",
        limit_probe=probe,
        limit_check_interval_s=0.3,
    ):
        wait_for(lambda: job(sessions, job_id).status is JobStatus.SUCCEEDED)

    assert probe.called == [CLAUDE]
