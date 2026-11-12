"""Job handlers of the planning states: `plan.brief`, `plan.research`, `plan.script`.

Each one is one skill call through the planner service (design doc section 6). The answer
becomes the job's output, under `document`, and the next skill reads it from there. Every
model call that was made is stored with its tokens and cost, also the first one of a
corrective retry (FR-17).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.runner import Handler, JobContext
from packages.adapters.llm.base import LLMAdapter
from packages.core import usage
from packages.core.db.models import Channel, Episode, Job
from packages.core.enums import ErrorClass, JobStatus
from packages.core.queue import JobError
from packages.skills import rules
from packages.skills.planner import Check, Repair, SkillResult, load_skill, run_skill

# The job type that produced each document a later skill needs.
BRIEF_JOB, RESEARCH_JOB, SCRIPT_JOB = "plan.brief", "plan.research", "plan.script"


def _episode(session: Session, episode_id: uuid.UUID | None) -> tuple[Episode, Channel]:
    episode = session.get(Episode, episode_id) if episode_id is not None else None
    if episode is None:
        raise JobError("A planning job needs an episode.", error_class=ErrorClass.BUG)
    channel = session.get(Channel, episode.channel_id)
    assert channel is not None  # noqa: S101 - the foreign key guarantees it
    return episode, channel


def document_of(session: Session, episode_id: uuid.UUID, job_type: str) -> dict[str, Any]:
    """The newest answer of an earlier planning job of this episode."""
    output = session.scalar(
        select(Job.output)
        .where(
            Job.episode_id == episode_id,
            Job.type == job_type,
            Job.status == JobStatus.SUCCEEDED,
        )
        .order_by(Job.finished_at.desc(), Job.created_at.desc())
        .limit(1)
    )
    if not isinstance(output, dict) or not isinstance(output.get("document"), dict):
        raise JobError(
            f"This job needs the result of '{job_type}', and the episode has none yet.",
            error_class=ErrorClass.BUG,
        )
    document: dict[str, Any] = output["document"]
    return document


def _brief_input(session: Session, episode: Episode, channel: Channel) -> dict[str, Any]:
    past = session.scalars(
        select(Episode.title)
        .where(
            Episode.channel_id == channel.id, Episode.id != episode.id, Episode.title.is_not(None)
        )
        .order_by(Episode.created_at.desc())
        .limit(50)
    ).all()
    return {
        "idea": episode.idea,
        "channel": {
            "name": channel.name,
            "motto": channel.motto,
            "target_duration_s": channel.target_duration_s,
        },
        "past_titles": [title for title in past if title],
    }


def _research_input(session: Session, episode: Episode, channel: Channel) -> dict[str, Any]:
    return {"brief": document_of(session, episode.id, BRIEF_JOB)}


def _script_input(session: Session, episode: Episode, channel: Channel) -> dict[str, Any]:
    return {
        "brief": document_of(session, episode.id, BRIEF_JOB),
        "claims": document_of(session, episode.id, RESEARCH_JOB),
        "target_duration_s": channel.target_duration_s,
        "voice_speed": channel.voice_speed,
    }


Inputs = Callable[[Session, Episode, Channel], dict[str, Any]]


def plan_handlers(
    sessions: sessionmaker[Session], llm: Callable[[], LLMAdapter]
) -> dict[str, Handler]:
    """The handlers, for a worker that has a database and a way to get the mode's model.

    `llm` is called for every job, so the owner's "Use paid APIs" switch is read as it is
    at that moment.
    """

    def handler(
        skill_name: str, inputs: Inputs, *, check: Check | None = None, repair: Repair | None = None
    ) -> Handler:
        def run(context: JobContext) -> Mapping[str, Any]:
            with sessions.begin() as session:
                episode, channel = _episode(session, context.job.episode_id)
                given = inputs(session, episode, channel)
            skill = load_skill(skill_name)
            result = run_skill(llm(), skill, given, check=check, repair=repair)
            _record(sessions, context, result)
            return {
                "skill": result.skill,
                "skill_version": result.skill_version,
                "document": result.output,
                "removed": list(result.removed),
            }

        return run

    return {
        BRIEF_JOB: handler("brief", _brief_input),
        RESEARCH_JOB: handler("research", _research_input, repair=rules.keep_sourced_claims),
        SCRIPT_JOB: handler("script", _script_input, check=rules.script_fits),
    }


def _record(sessions: sessionmaker[Session], context: JobContext, result: SkillResult) -> None:
    with sessions.begin() as session:
        for call in result.calls:
            usage.record_model_call(
                session,
                provider=call.provider,
                model=call.model,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                cost_usd=call.cost_usd,
                latency_ms=call.latency_ms,
                skill=result.skill,
                skill_version=result.skill_version,
                input_hash=context.job.input_hash,
                job_id=context.job.id,
            )
