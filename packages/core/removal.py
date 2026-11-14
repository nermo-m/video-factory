"""Deleting a video (Director mode design, "Deleting videos").

Deleting has two steps, so that it answers at once and never pulls files from under a job
that is running:

* `mark_deleted` hides the episode and cancels what is still queued.
* `purge` removes its rows and files. It waits while a job of the episode is running. The
  worker calls it again when that job ends.

What stays: the pictures of the channel's library, and the usage counts, because the plan
budgets are measured against them. The functions take a Session and never commit.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from packages.core.db.models import (
    AgentRun,
    AgentStep,
    Asset,
    AssetVersion,
    Claim,
    Episode,
    Job,
    ModelCall,
    ProviderUsage,
    Render,
    Review,
    SpecVersion,
)
from packages.core.enums import JobStatus
from packages.core.storage import StorageAdapter


def episode_folder(episode_id: uuid.UUID) -> PurePosixPath:
    """Where an episode's own files live: job outputs, scene files and uploads."""
    return PurePosixPath("episodes") / str(episode_id)


def is_deleted(session: Session, episode_id: uuid.UUID) -> bool:
    """True when the episode is marked as deleted or is already gone."""
    found = session.execute(
        select(Episode.deleted_at).where(Episode.id == episode_id)
    ).one_or_none()
    return found is None or found[0] is not None


def mark_deleted(session: Session, episode_id: uuid.UUID) -> bool:
    """Hide the episode and cancel its queued jobs. False when there is no such episode.
    A second call changes nothing."""
    episode = session.execute(
        select(Episode).where(Episode.id == episode_id).with_for_update()
    ).scalar_one_or_none()
    if episode is None:
        return False
    if episode.deleted_at is None:
        episode.deleted_at = func.now()
    session.execute(
        update(Job)
        .where(Job.episode_id == episode_id, Job.status == JobStatus.QUEUED)
        .values(status=JobStatus.CANCELLED, finished_at=func.now())
    )
    session.flush()
    return True


def purge(session: Session, storage: StorageAdapter, episode_id: uuid.UUID) -> bool:
    """Remove a deleted episode's rows and files. True when it is gone afterwards.

    Nothing is removed for an episode that is not marked as deleted, or while one of its
    jobs is running.
    """
    episode = session.execute(
        select(Episode).where(Episode.id == episode_id).with_for_update()
    ).scalar_one_or_none()
    if episode is None:
        return True
    if episode.deleted_at is None:
        return False
    running = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.episode_id == episode_id, Job.status == JobStatus.RUNNING)
    )
    if running:
        return False

    own_assets = select(Asset.id).where(Asset.episode_id == episode_id)
    own_jobs = select(Job.id).where(Job.episode_id == episode_id)
    own_runs = select(AgentRun.id).where(AgentRun.episode_id == episode_id)
    files = [
        path
        for path in session.scalars(
            select(AssetVersion.file_path).where(AssetVersion.asset_id.in_(own_assets))
        )
        if path
    ]

    episode.current_spec_id = None
    session.flush()
    session.execute(delete(AgentStep).where(AgentStep.agent_run_id.in_(own_runs)))
    session.execute(delete(AgentRun).where(AgentRun.episode_id == episode_id))
    session.execute(delete(Review).where(Review.episode_id == episode_id))
    session.execute(delete(Render).where(Render.episode_id == episode_id))
    session.execute(delete(Claim).where(Claim.episode_id == episode_id))
    session.execute(delete(AssetVersion).where(AssetVersion.asset_id.in_(own_assets)))
    session.execute(delete(Asset).where(Asset.episode_id == episode_id))
    for counted in (ModelCall, ProviderUsage):
        session.execute(update(counted).where(counted.job_id.in_(own_jobs)).values(job_id=None))
    session.execute(delete(Job).where(Job.episode_id == episode_id))
    # A version points at the one before it, so the chain is cut before it is removed.
    session.execute(
        update(SpecVersion).where(SpecVersion.episode_id == episode_id).values(parent_id=None)
    )
    session.execute(delete(SpecVersion).where(SpecVersion.episode_id == episode_id))
    session.delete(episode)
    session.flush()

    # Files last: when a row cannot be removed, nothing on disk has been touched yet.
    folder = episode_folder(episode_id)
    storage.remove_tree(folder)
    for path in files:
        if folder not in PurePosixPath(path).parents:
            storage.remove_tree(path)
    return True
