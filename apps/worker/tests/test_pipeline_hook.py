"""The worker tells the pipeline when a job has succeeded (design doc section 3.2).

Storing the result and moving the episode on happen in one transaction, so an episode
never has a finished state and nothing queued after it.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.runner import Handler, JobContext
from apps.worker.tests.test_worker import running_worker
from packages.core import pipeline
from packages.core.db import models
from packages.core.enums import EpisodeState, JobStatus

pytestmark = pytest.mark.integration


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


def done(_context: JobContext) -> dict[str, Any]:
    return {"ok": True}


def planning_handlers() -> dict[str, Handler]:
    return dict.fromkeys(("plan.research", "plan.shotlist"), done)


def wait_until(
    sessions: sessionmaker[Session],
    episode_id: uuid.UUID,
    reached: Callable[[models.Episode], bool],
    timeout_s: float = 15,
) -> models.Episode:
    deadline = time.monotonic() + timeout_s
    while True:
        with sessions() as session:
            episode = session.get(models.Episode, episode_id)
            assert episode is not None
            if reached(episode):
                return episode
        if time.monotonic() > deadline:
            pytest.fail(f"the episode stayed in {episode.state}")
        time.sleep(0.02)


def job_types(sessions: sessionmaker[Session], episode_id: uuid.UUID) -> dict[str, JobStatus]:
    with sessions() as session:
        found = session.scalars(select(models.Job).where(models.Job.episode_id == episode_id))
        return {job.type: job.status for job in found}


def test_an_episode_runs_from_the_idea_to_the_plan_gate_by_itself(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)

    with running_worker(sessions, planning_handlers()):
        episode = wait_until(sessions, episode_id, lambda found: found.awaiting_approval)

    assert episode.state is EpisodeState.DIRECTION
    # One job plans a video. Research is not run unless the episode asks for it.
    assert job_types(sessions, episode_id) == {"plan.shotlist": JobStatus.SUCCEEDED}


def test_a_job_keeps_its_result_when_the_pipeline_cannot_move_on(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pipeline refuses to move on after the job, as it does when the next state needs
    # something that is not there.
    tell_the_pipeline = pipeline.job_succeeded

    def refuses(_session: Session, _job_id: uuid.UUID, **_options: Any) -> None:
        raise pipeline.PipelineError("no_spec", "The next state needs the episode's spec.")

    monkeypatch.setattr(pipeline, "job_succeeded", refuses)
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)
    with running_worker(sessions, planning_handlers()):
        deadline = time.monotonic() + 15
        while job_types(sessions, episode_id).get("plan.shotlist") is not JobStatus.SUCCEEDED:
            assert time.monotonic() < deadline, "the shot list job did not finish"
            time.sleep(0.02)

    with sessions() as session:
        episode = session.get(models.Episode, episode_id)
        job = session.scalars(select(models.Job).where(models.Job.episode_id == episode_id)).one()
    assert episode is not None
    assert (episode.state, episode.awaiting_approval) == (EpisodeState.DIRECTION, False)
    assert job.output == {"ok": True}

    # Once the pipeline can move again, advancing by hand picks up where it stopped.
    monkeypatch.setattr(pipeline, "job_succeeded", tell_the_pipeline)
    with sessions.begin() as session:
        moved = pipeline.advance(session, episode_id)

    assert (moved.state, moved.awaiting_approval) == (EpisodeState.DIRECTION, True)


def test_the_worker_passes_on_whether_the_critic_is_switched_on(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        # As if the episode had got as far as the export, and the checks are run again.
        episode.state = EpisodeState.EXPORT
        pipeline.rerun(session, episode_id, EpisodeState.QC)

    with running_worker(sessions, {"qc.run": done}, critic_enabled=False):
        episode = wait_until(sessions, episode_id, lambda found: found.awaiting_approval)

    assert episode.state is EpisodeState.CRITIQUE
    assert "agent.critic" not in job_types(sessions, episode_id)
