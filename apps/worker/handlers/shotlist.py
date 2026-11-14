"""The job that plans a video in Director mode: `plan.shotlist`.

One model call reads the owner's prompt and writes the shot list. This job then checks it
against the prompt, builds the plan from it in ordinary code, stores the plan as the
episode's next spec version and gives every picture of the plan its row.

Nothing is forced on the video here. The look is the plain one, facts are only present
when the owner asked for research, and captions and music follow the episode's switches.
Lines that need more time than a video can have stop the job with a message for the
owner. They are never cut.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers.plan import RESEARCH_JOB, _episode, _record
from apps.worker.runner import Handler, JobContext
from packages.adapters.llm.base import LLMAdapter
from packages.core import assets
from packages.core.db.models import Job
from packages.core.enums import JobStatus, SpecAuthor
from packages.core.options import options_of
from packages.core.queue import NeedsOwnerError
from packages.core.specs import store_spec
from packages.render.theme import load_theme
from packages.skills import build, rules
from packages.skills.planner import load_skill, run_skill

SHOTLIST_JOB = "plan.shotlist"
MAX_TITLE = 200


def _claims(session: Session, episode_id: Any) -> list[dict[str, Any]]:
    """What research found for this episode, when research ran. Otherwise nothing."""
    output = session.scalar(
        select(Job.output)
        .where(
            Job.episode_id == episode_id,
            Job.type == RESEARCH_JOB,
            Job.status == JobStatus.SUCCEEDED,
        )
        .order_by(Job.finished_at.desc(), Job.created_at.desc())
        .limit(1)
    )
    document = output.get("document") if isinstance(output, dict) else None
    found = document.get("claims") if isinstance(document, dict) else None
    return [dict(claim) for claim in found] if isinstance(found, list) else []


def shotlist_handlers(
    sessions: sessionmaker[Session], llm: Callable[[], LLMAdapter]
) -> dict[str, Handler]:
    """The handler, for a worker that has a database and a way to get the mode's model.

    `llm` is called for every job, so the owner's "Use paid APIs" switch is read as it is
    at that moment.
    """

    def plan_shotlist(context: JobContext) -> Mapping[str, Any]:
        with sessions.begin() as session:
            episode, channel = _episode(session, context.job.episode_id)
            episode_id = episode.id
            options = options_of(episode.options)
            voice_id, voice_speed = channel.voice_id, channel.voice_speed
            # Research only reaches the plan when the owner asked for it for this video.
            claims = _claims(session, episode_id) if options.research else []
            inputs: dict[str, Any] = {
                "idea": episode.idea,
                "capabilities": load_theme(build.THEME).capabilities,
                "voice_speed": voice_speed,
                "claims": claims,
            }
            comment = context.job.input.get("comment")
            if isinstance(comment, str) and comment.strip():
                # What the owner asked to be different when they sent the plan back.
                inputs["comment"] = comment.strip()

        result = run_skill(
            llm(), load_skill("shotlist"), inputs, check=rules.shotlist_follows_the_owner
        )
        _record(sessions, context, result)

        try:
            spec = build.build_spec(
                result.output,
                episode_id=episode_id,
                voice_id=voice_id,
                voice_speed=voice_speed,
                captions=options.captions,
                music=options.music,
                claims=claims,
            )
        except build.TooLongError as too_long:
            raise NeedsOwnerError(str(too_long)) from too_long

        with sessions.begin() as session:
            stored = store_spec(
                session,
                episode_id,
                spec,
                author=SpecAuthor.MODEL,
                skill_version=result.skill_version,
            )
            episode, _channel = _episode(session, episode_id)
            title = str(result.output.get("title") or "").strip()
            if title and not episode.title:
                episode.title = title[:MAX_TITLE]
            # The length is what the scenes need, so the screens and the render agree on it.
            episode.target_duration_s = int(spec["format"]["target_duration_s"])
            # Every picture of the plan gets its row now, so the Assets tab can show what
            # will be made before anything is generated. There is no asset manifest in
            # Director mode: the plan's own entries are the whole truth.
            assets.sync(session, episode, spec, manifest={})
            version = stored.version

        return {
            "skill": result.skill,
            "skill_version": result.skill_version,
            "document": result.output,
            "removed": list(result.removed),
            "spec_version": version,
        }

    return {SHOTLIST_JOB: plan_shotlist}
