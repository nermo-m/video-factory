"""The worker tells the pipeline when a job has succeeded (design doc section 3.2).

Storing the result and moving the episode on happen in one transaction, so an episode
never has a finished state and nothing queued after it.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.runner import Handler, JobContext
from apps.worker.tests.test_worker import running_worker
from packages.core import pipeline, schemas
from packages.core.db import models
from packages.core.enums import EpisodeState, JobStatus, SpecAuthor, SpecKind

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
    return dict.fromkeys(
        ("plan.brief", "plan.research", "plan.script", "plan.direct", "plan.assets"), done
    )


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
    assert job_types(sessions, episode_id) == dict.fromkeys(
        ("plan.brief", "plan.research", "plan.script", "plan.direct"), JobStatus.SUCCEEDED
    )


def test_a_job_keeps_its_result_when_the_pipeline_cannot_move_on(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    # The plan is approved although no spec was ever stored. After the asset plan the
    # next state needs the spec and cannot start.
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)
    with running_worker(sessions, planning_handlers()):
        wait_until(sessions, episode_id, lambda found: found.awaiting_approval)
        with sessions.begin() as session:
            pipeline.approve(session, episode_id)
        deadline = time.monotonic() + 15
        while job_types(sessions, episode_id).get("plan.assets") is not JobStatus.SUCCEEDED:
            assert time.monotonic() < deadline, "the asset plan job did not finish"
            time.sleep(0.02)

    with sessions() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        assert episode.state is EpisodeState.ASSET_PLAN

    # Once the spec is there, advancing by hand picks up where the pipeline stopped.
    path = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid" / "all_scene_kinds.json"
    with sessions.begin() as session:
        version = models.SpecVersion(
            episode_id=episode_id,
            version=1,
            kind=SpecKind.AUTHORED,
            body=json.loads(path.read_text(encoding="utf-8")),
            author=SpecAuthor.MODEL,
        )
        session.add(version)
        session.flush()
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        episode.current_spec_id = version.id
    with sessions.begin() as session:
        moved = pipeline.advance(session, episode_id)

    assert moved.state is EpisodeState.ASSET_GEN


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
