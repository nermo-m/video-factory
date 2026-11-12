"""Job handlers of the planning states (design doc sections 4.1 and 6).

`plan.brief`, `plan.research`, `plan.script`, `plan.direct`, `plan.assets`, `plan.package`
and `plan.revise`: each one is one skill call through the planner service. The answer
becomes the job's output, under `document`, and a later skill reads it from there. Every
model call that was made is stored with its tokens and cost, also the first one of a
corrective retry (FR-17).

`plan.direct` also stores its answer as a new version of the episode's spec and makes it
the current one, which is what the plan gate shows the owner.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.runner import Handler, JobContext
from packages.adapters.llm.base import LLMAdapter
from packages.core import usage
from packages.core.db.models import Channel, Episode, Job, SpecVersion
from packages.core.enums import ErrorClass, JobStatus, SpecAuthor
from packages.core.queue import JobError
from packages.core.specs import store_spec
from packages.render.theme import load_theme
from packages.skills import rules
from packages.skills.planner import Check, Repair, SkillResult, load_skill, run_skill

BRIEF_JOB, RESEARCH_JOB, SCRIPT_JOB = "plan.brief", "plan.research", "plan.script"
DIRECT_JOB, ASSETS_JOB, PACKAGE_JOB, REVISE_JOB = (
    "plan.direct",
    "plan.assets",
    "plan.package",
    "plan.revise",
)
SPEC_VERSION = "2.0"
WIDTH, HEIGHT, FPS = 1080, 1920, 30
_SAMPLE_SPEC = Path(__file__).resolve().parents[3] / "samples" / "lighthouse_keeper"


@dataclass(frozen=True)
class Prepared:
    """What one planning job hands to the planner."""

    inputs: dict[str, Any]
    check: Check | None = None
    repair: Repair | None = None


def library_index() -> list[dict[str, Any]]:
    """The pictures that already exist and may be reused.

    Until the asset library of milestone M3 exists, these are the pictures bundled with
    the sample episode.
    """
    spec = json.loads((_SAMPLE_SPEC / "episode_spec.json").read_text(encoding="utf-8"))
    return [
        {
            "key": asset["id"],
            "kind": asset["kind"],
            "tags": asset.get("tags", []),
            "licence": asset.get("licence", ""),
        }
        for asset in spec["assets"]
        if asset["origin"] == "library"
    ]


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


def current_spec(session: Session, episode: Episode) -> dict[str, Any]:
    version = session.get(SpecVersion, episode.current_spec_id) if episode.current_spec_id else None
    if version is None:
        raise JobError(
            "This job needs the episode's spec, and the episode has none yet.",
            error_class=ErrorClass.BUG,
        )
    return dict(version.body)


def _length(episode: Episode, channel: Channel) -> int:
    """The episode's own target length, or the channel's when it has none."""
    return episode.target_duration_s or channel.target_duration_s


def _channel(episode: Episode, channel: Channel) -> dict[str, Any]:
    return {
        "name": channel.name,
        "motto": channel.motto,
        "target_duration_s": _length(episode, channel),
    }


def _brief(session: Session, episode: Episode, channel: Channel, _job: JobContext) -> Prepared:
    past = session.scalars(
        select(Episode.title)
        .where(
            Episode.channel_id == channel.id, Episode.id != episode.id, Episode.title.is_not(None)
        )
        .order_by(Episode.created_at.desc())
        .limit(50)
    ).all()
    return Prepared(
        {
            "idea": episode.idea,
            "channel": _channel(episode, channel),
            "past_titles": [title for title in past if title],
        }
    )


def _research(session: Session, episode: Episode, _channel_: Channel, _job: JobContext) -> Prepared:
    return Prepared(
        {"brief": document_of(session, episode.id, BRIEF_JOB)}, repair=rules.keep_sourced_claims
    )


def _script(session: Session, episode: Episode, channel: Channel, _job: JobContext) -> Prepared:
    return Prepared(
        {
            "brief": document_of(session, episode.id, BRIEF_JOB),
            "claims": document_of(session, episode.id, RESEARCH_JOB),
            "target_duration_s": _length(episode, channel),
            "voice_speed": channel.voice_speed,
        },
        check=rules.script_fits,
    )


def _direct(session: Session, episode: Episode, channel: Channel, _job: JobContext) -> Prepared:
    claims = document_of(session, episode.id, RESEARCH_JOB)
    # What the app knows is written into the spec as it is, whatever the model answers.
    fixed = {
        "spec_version": SPEC_VERSION,
        "episode_id": str(episode.id),
        "format": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "target_duration_s": _length(episode, channel),
        },
        "theme": channel.theme,
        "voice": {"voice_id": channel.voice_id, "speed": channel.voice_speed},
        # The same episode always gets the same seed, so a re-run draws the same frames.
        "seed": episode.id.int % 2**32,
        "claims": claims["claims"],
    }
    return Prepared(
        {
            "script": document_of(session, episode.id, SCRIPT_JOB),
            "brief": document_of(session, episode.id, BRIEF_JOB),
            "claims": claims,
            "capabilities": load_theme(channel.theme).capabilities,
            "library": library_index(),
            "channel": _channel(episode, channel),
        },
        check=rules.spec_follows_the_plan,
        repair=rules.complete_spec(fixed),
    )


def _assets(session: Session, episode: Episode, channel: Channel, _job: JobContext) -> Prepared:
    spec = current_spec(session, episode)
    return Prepared(
        {"spec": spec, "library": library_index(), "style_block": channel.style_block},
        check=rules.manifest_covers_the_spec,
        repair=rules.complete_spec({"episode_id": spec["episode_id"]}),
    )


def _package(session: Session, episode: Episode, _channel_: Channel, _job: JobContext) -> Prepared:
    return Prepared(
        {
            "spec": current_spec(session, episode),
            "brief": document_of(session, episode.id, BRIEF_JOB),
        },
        check=rules.package_fits_the_video,
    )


def _revise(session: Session, episode: Episode, channel: Channel, job: JobContext) -> Prepared:
    comment = job.job.input.get("comment")
    if not isinstance(comment, str) or not comment.strip():
        raise JobError("A revision needs the owner's comment.", error_class=ErrorClass.BUG)
    return Prepared(
        {
            "spec": current_spec(session, episode),
            "comment": comment,
            "capabilities": load_theme(channel.theme).capabilities,
        },
        check=rules.patch_leaves_a_valid_spec,
    )


Prepare = Callable[[Session, Episode, Channel, JobContext], Prepared]
_JOBS: dict[str, tuple[str, Prepare]] = {
    BRIEF_JOB: ("brief", _brief),
    RESEARCH_JOB: ("research", _research),
    SCRIPT_JOB: ("script", _script),
    DIRECT_JOB: ("direct", _direct),
    ASSETS_JOB: ("assets", _assets),
    PACKAGE_JOB: ("package", _package),
    REVISE_JOB: ("revise", _revise),
}


def plan_handlers(
    sessions: sessionmaker[Session], llm: Callable[[], LLMAdapter]
) -> dict[str, Handler]:
    """The handlers, for a worker that has a database and a way to get the mode's model.

    `llm` is called for every job, so the owner's "Use paid APIs" switch is read as it is
    at that moment.
    """

    def handler(job_type: str) -> Handler:
        skill_name, prepare = _JOBS[job_type]

        def run(context: JobContext) -> Mapping[str, Any]:
            with sessions.begin() as session:
                episode, channel = _episode(session, context.job.episode_id)
                prepared = prepare(session, episode, channel, context)
                episode_id = episode.id
            result = run_skill(
                llm(),
                load_skill(skill_name),
                prepared.inputs,
                check=prepared.check,
                repair=prepared.repair,
            )
            _record(sessions, context, result)
            output: dict[str, Any] = {
                "skill": result.skill,
                "skill_version": result.skill_version,
                "document": result.output,
                "removed": list(result.removed),
            }
            if job_type == DIRECT_JOB:
                with sessions.begin() as session:
                    stored = store_spec(
                        session,
                        episode_id,
                        result.output,
                        author=SpecAuthor.MODEL,
                        skill_version=result.skill_version,
                    )
                    output["spec_version"] = stored.version
            return output

        return run

    return {job_type: handler(job_type) for job_type in _JOBS}


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
