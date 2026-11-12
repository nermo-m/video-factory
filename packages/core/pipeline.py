"""The pipeline state machine on the database (design doc sections 4.1 and 4.2).

The rules of section 4.2, and where each one lives here:

* "A state advances only when all of its jobs have succeeded." `job_succeeded` is called
  when a job's result is stored. It moves on only when every job of the current stage of
  the current run has succeeded.
* "A gate sets awaiting_approval=true. Approve advances. Reject requires a comment and
  returns to the state named in the reject action." `approve` and `reject`.
* "Any state can be re-run. Re-running a state marks all later states stale but deletes
  nothing." `rerun`. Jobs that were still waiting are cancelled, never removed.
* "Editing the spec after plan approval marks only the affected scenes stale."
  `spec_edited`. The voice and render states then make only those scenes again.

How a state's jobs are told apart: every job the pipeline creates carries `state`, `stage`
and `run` in its input. A state's current run is its highest run number, and only the jobs
of that run's latest stage decide whether the state moves on. A re-run cancels what was
still waiting or running, so a late result from an earlier run is never stored at all.

Every function takes a Session and never commits: the caller owns the transaction. Each
one locks the episode row first, so two things that happen at the same moment are applied
one after the other.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.core import queue
from packages.core.db.models import Episode, Job, SpecVersion
from packages.core.enums import EpisodeState, JobStatus
from packages.core.stages import (
    GATES,
    REJECT_RETURNS_TO,
    index_of,
    next_state,
    plan_stage,
    stage_count,
)
from packages.core.stale import StaleScenes, affected_scenes

_UNFINISHED = (JobStatus.QUEUED, JobStatus.RUNNING)


class PipelineError(Exception):
    """The episode cannot do what was asked. `code` is stable, the message is for people."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- what the owner and the interface ask for --------------------------------------------


def advance(session: Session, episode_id: uuid.UUID, *, critic_enabled: bool = True) -> Episode:
    """Start the pipeline from `idea`, or move on when the current state has finished.

    The pipeline moves on by itself as jobs succeed, so this is needed at the start, and
    after something stopped it from noticing that a state had finished.
    """
    episode = _locked(session, episode_id)
    if episode.state is EpisodeState.DONE:
        raise PipelineError("finished", "This episode is finished. There is no next state.")
    if episode.awaiting_approval:
        raise PipelineError(
            "awaiting_approval",
            f"The episode waits for the {GATES[episode.state]} approval. Approve or reject it.",
        )
    run, stage, statuses = _current(session, episode)
    if run is None:
        following = next_state(episode.state)
        assert following is not None  # noqa: S101 - done was handled above
        _enter(session, episode, following, critic_enabled=critic_enabled)
        return episode
    open_jobs = Counter(status.value for status in statuses if status is not JobStatus.SUCCEEDED)
    if open_jobs:
        counted = ", ".join(f"{count} {status}" for status, count in sorted(open_jobs.items()))
        raise PipelineError(
            "jobs_unfinished",
            f"The state '{episode.state.value}' still has jobs that have not succeeded: "
            f"{counted}. Retry the failed jobs or run the state again.",
        )
    _start_stage(session, episode, run, stage + 1, critic_enabled=critic_enabled)
    return episode


def approve(session: Session, episode_id: uuid.UUID, *, critic_enabled: bool = True) -> Episode:
    """Pass the gate the episode is waiting at."""
    episode = _at_gate(session, episode_id)
    episode.awaiting_approval = False
    following = next_state(episode.state)
    assert following is not None  # noqa: S101 - the last state is not a gate
    _enter(session, episode, following, critic_enabled=critic_enabled)
    return episode


def reject(
    session: Session,
    episode_id: uuid.UUID,
    *,
    comment: str,
    return_to_state: EpisodeState | None = None,
    critic_enabled: bool = True,
) -> Episode:
    """Turn down what is at the gate and run a state again with the owner's comment.

    Without `return_to_state` that is the state that produced what was rejected.
    """
    episode = _at_gate(session, episode_id)
    if not comment.strip():
        raise PipelineError("comment_required", "A rejection needs a comment that says why.")
    target = return_to_state or REJECT_RETURNS_TO[episode.state]
    _run_again(session, episode, target, comment=comment.strip(), critic_enabled=critic_enabled)
    return episode


def rerun(
    session: Session,
    episode_id: uuid.UUID,
    state: EpisodeState,
    *,
    critic_enabled: bool = True,
) -> Episode:
    """Run a state again. Later states are marked stale. Nothing is deleted."""
    episode = _locked(session, episode_id)
    _run_again(session, episode, state, comment=None, critic_enabled=critic_enabled)
    return episode


def spec_edited(
    session: Session,
    episode_id: uuid.UUID,
    old: dict[str, Any],
    new: dict[str, Any],
) -> StaleScenes:
    """Record which scenes an edit of the authored spec has made stale.

    Only marks. Nothing is run until a state is run again. Returns what this edit marked.
    Before the plan is approved, and for outputs that do not exist yet, there is nothing
    to mark: the states ahead will use the edited spec anyway.
    """
    episode = _locked(session, episode_id)
    if index_of(episode.state) <= index_of(EpisodeState.DIRECTION):
        return StaleScenes()
    found = affected_scenes(old, new)
    marked = StaleScenes(
        voice=found.voice if _has_outputs(session, episode, EpisodeState.VOICE) else (),
        render=found.render if _has_outputs(session, episode, EpisodeState.RENDER) else (),
    )
    if not marked:
        return marked
    order = [scene["id"] for scene in new["scenes"]]
    episode.stale_scenes = (
        StaleScenes.from_json(episode.stale_scenes).merged(marked, order=order).to_json()
    )
    first = EpisodeState.VOICE if marked.voice else EpisodeState.RENDER
    current = episode.stale_from_state
    if current is None or index_of(current) > index_of(first):
        episode.stale_from_state = first
    return marked


# --- what the worker reports -------------------------------------------------------------


def job_succeeded(
    session: Session, job_id: uuid.UUID, *, critic_enabled: bool = True
) -> Episode | None:
    """Tell the pipeline that a job's result has been stored.

    Call it in the transaction that stored the result. Returns the episode, or None when
    the job belongs to no episode. Calling it again for the same job changes nothing.
    """
    job = session.get(Job, job_id, populate_existing=True)
    if job is None or job.episode_id is None or job.status is not JobStatus.SUCCEEDED:
        return None
    if "state" not in job.input:
        return None
    episode = _locked(session, job.episode_id)
    if episode.awaiting_approval or episode.state.value != job.input["state"]:
        return episode
    run, stage, statuses = _current(session, episode)
    if run is not None and all(status is JobStatus.SUCCEEDED for status in statuses):
        _start_stage(session, episode, run, stage + 1, critic_enabled=critic_enabled)
    return episode


# --- steps -------------------------------------------------------------------------------


def _locked(session: Session, episode_id: uuid.UUID) -> Episode:
    episode = session.execute(
        select(Episode)
        .where(Episode.id == episode_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if episode is None:
        raise PipelineError("not_found", f"There is no episode {episode_id}.")
    return episode


def _at_gate(session: Session, episode_id: uuid.UUID) -> Episode:
    episode = _locked(session, episode_id)
    if not episode.awaiting_approval:
        raise PipelineError(
            "not_awaiting_approval",
            f"The episode is in '{episode.state.value}' and is not waiting for an approval.",
        )
    return episode


def _of_state(episode: Episode, state: EpisodeState) -> Any:
    return (Job.episode_id == episode.id) & (Job.input["state"].astext == state.value)


def _current(session: Session, episode: Episode) -> tuple[int | None, int, list[JobStatus]]:
    """The current run of the episode's state, its latest stage, and that stage's jobs."""
    in_state = _of_state(episode, episode.state)
    run = session.scalar(select(func.max(Job.input["run"].as_integer())).where(in_state))
    if run is None:
        return None, 0, []
    in_run = in_state & (Job.input["run"].as_integer() == run)
    stage = session.scalar(select(func.max(Job.input["stage"].as_integer())).where(in_run))
    statuses = session.scalars(
        select(Job.status).where(in_run & (Job.input["stage"].as_integer() == stage))
    ).all()
    return run, int(stage or 0), list(statuses)


def _has_outputs(session: Session, episode: Episode, state: EpisodeState) -> bool:
    """True when the state has finished work from this or an earlier run."""
    found = session.scalar(
        select(Job.id)
        .where(_of_state(episode, state) & (Job.status == JobStatus.SUCCEEDED))
        .limit(1)
    )
    return found is not None


def _first_with_outputs(
    session: Session, episode: Episode, *, after: EpisodeState
) -> EpisodeState | None:
    """The first state after `after` whose finished work would now be out of date."""
    state = next_state(after)
    while state is not None:
        if _has_outputs(session, episode, state):
            return state
        state = next_state(state)
    return None


def _spec(session: Session, episode: Episode) -> dict[str, Any] | None:
    if episode.current_spec_id is None:
        return None
    version = session.get(SpecVersion, episode.current_spec_id)
    return dict(version.body) if version is not None else None


def _enter(
    session: Session,
    episode: Episode,
    state: EpisodeState,
    *,
    critic_enabled: bool,
    comment: str | None = None,
) -> None:
    """Put the episode into a state and queue the jobs of its first stage."""
    episode.state = state
    episode.awaiting_approval = False
    earlier = session.scalar(
        select(func.max(Job.input["run"].as_integer())).where(_of_state(episode, state))
    )
    _start_stage(
        session, episode, (earlier or 0) + 1, 0, critic_enabled=critic_enabled, comment=comment
    )


def _start_stage(
    session: Session,
    episode: Episode,
    run: int,
    stage: int,
    *,
    critic_enabled: bool,
    comment: str | None = None,
) -> None:
    """Queue the jobs of a stage. Stages with nothing to do are passed over, and after the
    last stage the state is finished."""
    state = episode.state
    scope = StaleScenes.from_json(episode.stale_scenes)
    while stage < stage_count(state):
        try:
            requests = plan_stage(
                state,
                stage,
                spec=_spec(session, episode),
                critic_enabled=critic_enabled,
                scope=scope,
            )
        except ValueError as error:
            raise PipelineError("no_spec", str(error)) from error
        if requests:
            for request in requests:
                payload = {**request.payload, "state": state.value, "stage": stage, "run": run}
                if comment is not None:
                    payload["comment"] = comment
                queue.enqueue(
                    session,
                    job_type=request.job_type,
                    tag=request.tag,
                    payload=payload,
                    episode_id=episode.id,
                )
            return
        stage += 1
    _finish_state(session, episode, critic_enabled=critic_enabled)


def _finish_state(session: Session, episode: Episode, *, critic_enabled: bool) -> None:
    """Every job of the state has succeeded: clear what is no longer stale, then stop at a
    gate or enter the next state."""
    state = episode.state
    scenes = StaleScenes.from_json(episode.stale_scenes)
    if state is EpisodeState.VOICE:
        scenes = StaleScenes(render=scenes.render)
    elif state is EpisodeState.RENDER:
        scenes = StaleScenes(voice=scenes.voice)
    episode.stale_scenes = scenes.to_json() if scenes else {}

    marker = episode.stale_from_state
    if marker is not None and index_of(marker) <= index_of(state):
        episode.stale_from_state = _first_with_outputs(session, episode, after=state)

    if state in GATES:
        episode.awaiting_approval = True
        return
    following = next_state(state)
    if following is not None:
        _enter(session, episode, following, critic_enabled=critic_enabled)


def _run_again(
    session: Session,
    episode: Episode,
    state: EpisodeState,
    *,
    comment: str | None,
    critic_enabled: bool,
) -> None:
    if stage_count(state) == 0:
        raise PipelineError(
            "invalid_state", f"The state '{state.value}' has no jobs, so it cannot be run again."
        )
    if index_of(state) > index_of(episode.state):
        raise PipelineError(
            "invalid_state",
            f"The episode is in '{episode.state.value}' and has not reached '{state.value}' yet.",
        )

    # What was still waiting or running in the current state is no longer wanted.
    run, _, _ = _current(session, episode)
    if run is not None:
        unfinished = session.scalars(
            select(Job.id).where(
                _of_state(episode, episode.state)
                & (Job.input["run"].as_integer() == run)
                & Job.status.in_(_UNFINISHED)
            )
        ).all()
        for job_id in unfinished:
            queue.cancel(session, job_id)

    marker = episode.stale_from_state
    if marker is None or index_of(marker) >= index_of(state):
        episode.stale_from_state = _first_with_outputs(session, episode, after=state)
    if index_of(state) < index_of(EpisodeState.VOICE):
        # Everything from here on is made again in full.
        episode.stale_scenes = {}
    _enter(session, episode, state, critic_enabled=critic_enabled, comment=comment)
