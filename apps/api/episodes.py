"""Episodes: lifecycle, spec versions, diff and revision (design doc sections 4, 10, FR-03).

    GET  /episodes                         the Board, newest first, paged
    POST /episodes                         create from an idea, and start planning
    GET  /episodes/{id}                    state, gate, stale marker, latest jobs
    POST /episodes/{id}/advance            run the next state
    POST /episodes/{id}/approve            pass the current gate
    POST /episodes/{id}/reject             comment, optional state to return to
    POST /episodes/{id}/rerun              run a state again
    GET  /episodes/{id}/spec               the current authored spec
    PUT  /episodes/{id}/spec               replace it: checked, stored as a new version
    GET  /episodes/{id}/spec/versions      history
    GET  /episodes/{id}/spec/diff          what changed between two versions
    POST /episodes/{id}/revise             ask for a change in words. Queues the revise skill
    GET  /episodes/{id}/revisions/{job_id} the proposed patch and what it would change
    POST /episodes/{id}/revise/apply       apply a proposal the owner has seen

A revision is a model call, so it runs as a job in the worker like every other one: it is
counted, it waits when the provider is limited, and the API stays quick. The proposal is
applied only if the spec is still the version it was written for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.errors import BAD_BODY_RESPONSE, ApiError, ErrorResponse
from packages.core import pipeline, queue, schemas, specs
from packages.core.db.models import Channel, Episode, Job, SpecVersion
from packages.core.enums import EpisodeState, JobStatus, JobTag, SpecAuthor
from packages.core.stages import GATES
from packages.render.theme import check_capabilities, load_theme

router = APIRouter(tags=["episodes"])

REVISE_JOB = "plan.revise"
DEFAULT_CHANNEL = {"name": "My channel", "voice_id": "bm_george", "theme": "night_scrolls"}
JOBS_SHOWN = 50


# --- What travels ------------------------------------------------------------------------


class JobOut(BaseModel):
    id: uuid.UUID
    type: str
    status: JobStatus
    error_class: str | None
    error_message: str | None = Field(
        description="Why the job failed or waits, in words for the owner."
    )
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EpisodeOut(BaseModel):
    id: uuid.UUID
    title: str | None
    idea: str
    state: EpisodeState
    awaiting_approval: bool
    gate: str | None = Field(description="plan, assets or review while it waits for approval.")
    stale_from_state: EpisodeState | None
    stale_scenes: dict[str, list[str]]
    target_duration_s: int
    spec_version: int | None = Field(description="The current version of its spec, if it has one.")
    created_at: datetime


class EpisodeDetail(EpisodeOut):
    jobs: list[JobOut] = Field(description="The latest jobs, newest first.")


class EpisodeList(BaseModel):
    episodes: list[EpisodeOut]
    total: int
    limit: int
    offset: int


class EpisodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]
    target_duration_s: Literal[45, 60] = 45
    start: StrictBool = Field(default=True, description="Start planning at once.")


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]
    return_to_state: EpisodeState | None = None


class RerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: EpisodeState


class SpecOut(BaseModel):
    version: int
    author: SpecAuthor
    skill_version: str | None
    created_at: datetime
    spec: dict[str, Any]


class SpecVersionOut(BaseModel):
    version: int
    author: SpecAuthor
    skill_version: str | None
    created_at: datetime
    current: bool


class SpecVersions(BaseModel):
    versions: list[SpecVersionOut]


class ChangeOut(BaseModel):
    op: Literal["add", "remove", "replace"]
    path: str = Field(description="Where in the spec, as a JSON Pointer.")
    old: Any = None
    new: Any = None


class SpecDiff(BaseModel):
    from_version: int
    to_version: int
    changes: list[ChangeOut]


class ReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


class RevisionOut(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    base_version: int = Field(description="The spec version the proposal was written for.")
    comment: str
    summary: str | None = Field(description="What the proposal changes, in words.")
    patch: list[dict[str, Any]] | None = Field(description="The proposed JSON Patch.")
    changes: list[ChangeOut] | None = Field(
        description="What applying it would change. Null when it no longer fits the spec."
    )
    can_apply: bool
    message: str | None = Field(description="Why it failed, waits, or can no longer be applied.")


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: uuid.UUID


# --- The service ---------------------------------------------------------------------------


class EpisodeService(Protocol):
    """What the routes need. The real one works on the database."""

    def page(self, limit: int, offset: int) -> EpisodeList: ...
    def create(self, body: EpisodeCreate) -> EpisodeDetail: ...
    def get(self, episode_id: uuid.UUID) -> EpisodeDetail: ...
    def advance(self, episode_id: uuid.UUID) -> EpisodeDetail: ...
    def approve(self, episode_id: uuid.UUID) -> EpisodeDetail: ...
    def reject(self, episode_id: uuid.UUID, body: RejectRequest) -> EpisodeDetail: ...
    def rerun(self, episode_id: uuid.UUID, state: EpisodeState) -> EpisodeDetail: ...
    def spec(self, episode_id: uuid.UUID) -> SpecOut: ...
    def replace_spec(self, episode_id: uuid.UUID, body: dict[str, Any]) -> SpecOut: ...
    def versions(self, episode_id: uuid.UUID) -> SpecVersions: ...
    def diff(self, episode_id: uuid.UUID, from_version: int, to_version: int) -> SpecDiff: ...
    def revise(self, episode_id: uuid.UUID, comment: str) -> RevisionOut: ...
    def revision(self, episode_id: uuid.UUID, job_id: uuid.UUID) -> RevisionOut: ...
    def apply(self, episode_id: uuid.UUID, job_id: uuid.UUID) -> SpecOut: ...


def _not_found() -> ApiError:
    return ApiError(404, "episode_not_found", "This episode does not exist.")


def _spec_error(error: specs.SpecError) -> ApiError:
    if error.code == "not_found":
        return _not_found()
    if error.code == "no_spec":
        return ApiError(404, "no_spec", str(error))
    status = 422 if error.code == "invalid_spec" else 409
    return ApiError(status, error.code, str(error), details={"problems": error.problems})


def _cannot_draw(body: dict[str, Any]) -> list[str]:
    """What the spec's theme cannot draw. Expects a spec that already fits its schema."""
    try:
        theme = load_theme(str(body.get("theme")))
    except (KeyError, ValueError, OSError):
        return [f"/theme: there is no theme '{body.get('theme')}'"]
    return [str(found) for found in check_capabilities(body, theme.capabilities)]


def _spec_out(version: SpecVersion) -> SpecOut:
    return SpecOut(
        version=version.version,
        author=version.author,
        skill_version=version.skill_version,
        created_at=version.created_at,
        spec=dict(version.body),
    )


def _changes(old: Any, new: Any) -> list[ChangeOut]:
    return [
        ChangeOut(op=found.op, path=found.path, old=found.old, new=found.new)  # type: ignore[arg-type]
        for found in specs.diff(old, new)
    ]


class DatabaseEpisodeService:
    def __init__(self, sessions: sessionmaker[Session], *, critic_enabled: bool = True) -> None:
        self._sessions = sessions
        self._critic = critic_enabled

    # --- reading ---

    def _episode(self, session: Session, episode_id: uuid.UUID) -> Episode:
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise _not_found()
        return episode

    def _out(self, session: Session, episode: Episode) -> dict[str, Any]:
        channel = session.get(Channel, episode.channel_id)
        version = (
            session.get(SpecVersion, episode.current_spec_id) if episode.current_spec_id else None
        )
        return {
            "id": episode.id,
            "title": episode.title,
            "idea": episode.idea,
            "state": episode.state,
            "awaiting_approval": episode.awaiting_approval,
            "gate": GATES.get(episode.state) if episode.awaiting_approval else None,
            "stale_from_state": episode.stale_from_state,
            "stale_scenes": dict(episode.stale_scenes or {}),
            "target_duration_s": episode.target_duration_s
            or (channel.target_duration_s if channel else 45),
            "spec_version": version.version if version else None,
            "created_at": episode.created_at,
        }

    def _detail(self, session: Session, episode: Episode) -> EpisodeDetail:
        jobs = session.scalars(
            select(Job)
            .where(Job.episode_id == episode.id)
            .order_by(Job.created_at.desc(), Job.id)
            .limit(JOBS_SHOWN)
        ).all()
        return EpisodeDetail(
            **self._out(session, episode),
            jobs=[
                JobOut(
                    id=job.id,
                    type=job.type,
                    status=job.status,
                    error_class=job.error_class.value if job.error_class else None,
                    error_message=job.error_message,
                    attempts=job.attempts,
                    created_at=job.created_at,
                    started_at=job.started_at,
                    finished_at=job.finished_at,
                )
                for job in jobs
            ],
        )

    def page(self, limit: int, offset: int) -> EpisodeList:
        with self._sessions.begin() as session:
            total = session.scalar(select(func.count()).select_from(Episode)) or 0
            found = session.scalars(
                select(Episode)
                .order_by(Episode.created_at.desc(), Episode.id)
                .limit(limit)
                .offset(offset)
            ).all()
            return EpisodeList(
                episodes=[EpisodeOut(**self._out(session, episode)) for episode in found],
                total=total,
                limit=limit,
                offset=offset,
            )

    def get(self, episode_id: uuid.UUID) -> EpisodeDetail:
        with self._sessions.begin() as session:
            return self._detail(session, self._episode(session, episode_id))

    # --- lifecycle ---

    def create(self, body: EpisodeCreate) -> EpisodeDetail:
        with self._sessions.begin() as session:
            channel = session.scalars(
                select(Channel).order_by(Channel.created_at, Channel.id).limit(1)
            ).first()
            if channel is None:
                # The channel screens come later. Until then one channel holds the defaults.
                channel = Channel(**DEFAULT_CHANNEL)
                session.add(channel)
                session.flush()
            episode = Episode(
                channel_id=channel.id,
                idea=body.idea.strip(),
                target_duration_s=body.target_duration_s,
            )
            session.add(episode)
            session.flush()
            if body.start:
                pipeline.advance(session, episode.id, critic_enabled=self._critic)
            session.refresh(episode)
            return self._detail(session, episode)

    def _step(self, episode_id: uuid.UUID, step: Any) -> EpisodeDetail:
        with self._sessions.begin() as session:
            self._episode(session, episode_id)
            try:
                episode = step(session)
            except pipeline.PipelineError as error:
                raise ApiError(409, error.code, str(error)) from error
            session.flush()
            session.refresh(episode)
            return self._detail(session, episode)

    def advance(self, episode_id: uuid.UUID) -> EpisodeDetail:
        return self._step(
            episode_id, lambda s: pipeline.advance(s, episode_id, critic_enabled=self._critic)
        )

    def approve(self, episode_id: uuid.UUID) -> EpisodeDetail:
        return self._step(
            episode_id, lambda s: pipeline.approve(s, episode_id, critic_enabled=self._critic)
        )

    def reject(self, episode_id: uuid.UUID, body: RejectRequest) -> EpisodeDetail:
        return self._step(
            episode_id,
            lambda s: pipeline.reject(
                s,
                episode_id,
                comment=body.comment,
                return_to_state=body.return_to_state,
                critic_enabled=self._critic,
            ),
        )

    def rerun(self, episode_id: uuid.UUID, state: EpisodeState) -> EpisodeDetail:
        return self._step(
            episode_id,
            lambda s: pipeline.rerun(s, episode_id, state, critic_enabled=self._critic),
        )

    # --- spec ---

    def _current(self, session: Session, episode_id: uuid.UUID) -> SpecVersion:
        self._episode(session, episode_id)
        version = specs.current(session, episode_id)
        if version is None:
            raise ApiError(404, "no_spec", "This episode has no spec yet. The plan writes it.")
        return version

    def spec(self, episode_id: uuid.UUID) -> SpecOut:
        with self._sessions.begin() as session:
            return _spec_out(self._current(session, episode_id))

    def _store(
        self, session: Session, episode_id: uuid.UUID, body: dict[str, Any], author: SpecAuthor
    ) -> SpecOut:
        try:
            # The schema is checked first, so the theme check can rely on the spec's shape.
            problems = [] if schemas.validate("episode_spec", body) else _cannot_draw(body)
            stored = specs.replace_spec(
                session, episode_id, body, author=author, capability_problems=problems
            )
        except specs.SpecError as error:
            raise _spec_error(error) from error
        return _spec_out(stored)

    def replace_spec(self, episode_id: uuid.UUID, body: dict[str, Any]) -> SpecOut:
        with self._sessions.begin() as session:
            self._current(session, episode_id)
            return self._store(session, episode_id, body, SpecAuthor.OWNER)

    def versions(self, episode_id: uuid.UUID) -> SpecVersions:
        with self._sessions.begin() as session:
            episode = self._episode(session, episode_id)
            return SpecVersions(
                versions=[
                    SpecVersionOut(
                        version=found.version,
                        author=found.author,
                        skill_version=found.skill_version,
                        created_at=found.created_at,
                        current=found.id == episode.current_spec_id,
                    )
                    for found in specs.versions(session, episode_id)
                ]
            )

    def diff(self, episode_id: uuid.UUID, from_version: int, to_version: int) -> SpecDiff:
        with self._sessions.begin() as session:
            self._episode(session, episode_id)
            old = specs.version(session, episode_id, from_version)
            new = specs.version(session, episode_id, to_version)
            if old is None or new is None:
                missing = from_version if old is None else to_version
                raise ApiError(404, "version_not_found", f"The spec has no version {missing}.")
            return SpecDiff(
                from_version=from_version,
                to_version=to_version,
                changes=_changes(dict(old.body), dict(new.body)),
            )

    # --- revision ---

    def revise(self, episode_id: uuid.UUID, comment: str) -> RevisionOut:
        with self._sessions.begin() as session:
            version = self._current(session, episode_id)
            job = queue.enqueue(
                session,
                job_type=REVISE_JOB,
                tag=JobTag.CPU,
                payload={"comment": comment.strip(), "base_version": version.version},
                episode_id=episode_id,
            )
            session.flush()
            session.refresh(job)
            return self._revision(session, episode_id, job)

    def _job(self, session: Session, episode_id: uuid.UUID, job_id: uuid.UUID) -> Job:
        self._episode(session, episode_id)
        job = session.get(Job, job_id)
        if job is None or job.episode_id != episode_id or job.type != REVISE_JOB:
            raise ApiError(404, "revision_not_found", "This episode has no such revision.")
        return job

    def _revision(self, session: Session, episode_id: uuid.UUID, job: Job) -> RevisionOut:
        base = int(job.input.get("base_version", 0))
        document = (job.output or {}).get("document") if job.status is JobStatus.SUCCEEDED else None
        patch = document.get("patch") if isinstance(document, dict) else None
        changes, message = None, job.error_message
        if patch is not None:
            try:
                before = specs.current(session, episode_id)
                after = specs.patched(session, episode_id, patch, base)
                changes = _changes(dict(before.body) if before else {}, after)
            except specs.SpecError as error:
                message = str(error)
        return RevisionOut(
            job_id=job.id,
            status=job.status,
            base_version=base,
            comment=str(job.input.get("comment", "")),
            summary=document.get("summary") if isinstance(document, dict) else None,
            patch=patch,
            changes=changes,
            can_apply=changes is not None,
            message=message,
        )

    def revision(self, episode_id: uuid.UUID, job_id: uuid.UUID) -> RevisionOut:
        with self._sessions.begin() as session:
            return self._revision(session, episode_id, self._job(session, episode_id, job_id))

    def apply(self, episode_id: uuid.UUID, job_id: uuid.UUID) -> SpecOut:
        with self._sessions.begin() as session:
            job = self._job(session, episode_id, job_id)
            proposal = self._revision(session, episode_id, job)
            if proposal.patch is None:
                raise ApiError(
                    409, "revision_not_ready", "This revision has no proposal to apply yet."
                )
            try:
                body = specs.patched(session, episode_id, proposal.patch, proposal.base_version)
            except specs.SpecError as error:
                raise _spec_error(error) from error
            return self._store(session, episode_id, body, SpecAuthor.MODEL)


class MemoryEpisodeService:
    """Episodes without a database, for tests of the routes and for the OpenAPI export.

    It keeps what is created and can show it. Everything that needs the pipeline answers
    that the episode does not exist.
    """

    def __init__(self) -> None:
        self.episodes: dict[uuid.UUID, EpisodeDetail] = {}

    def page(self, limit: int, offset: int) -> EpisodeList:
        found = sorted(self.episodes.values(), key=lambda e: e.created_at, reverse=True)
        return EpisodeList(
            episodes=[EpisodeOut(**e.model_dump(exclude={"jobs"})) for e in found][
                offset : offset + limit
            ],
            total=len(found),
            limit=limit,
            offset=offset,
        )

    def create(self, body: EpisodeCreate) -> EpisodeDetail:
        episode = EpisodeDetail(
            id=uuid.uuid4(),
            title=None,
            idea=body.idea.strip(),
            state=EpisodeState.BRIEF if body.start else EpisodeState.IDEA,
            awaiting_approval=False,
            gate=None,
            stale_from_state=None,
            stale_scenes={},
            target_duration_s=body.target_duration_s,
            spec_version=None,
            created_at=datetime.now(UTC),
            jobs=[],
        )
        self.episodes[episode.id] = episode
        return episode

    def get(self, episode_id: uuid.UUID) -> EpisodeDetail:
        if episode_id not in self.episodes:
            raise _not_found()
        return self.episodes[episode_id]

    def _missing(self, *_: Any) -> Any:
        raise _not_found()

    advance = approve = reject = rerun = spec = replace_spec = _missing
    versions = diff = revise = revision = apply = _missing


# --- Routes ------------------------------------------------------------------------------

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorResponse,
        "description": "The episode, or what was asked of it, does not exist.",
    },
}
CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "The episode cannot do this in its current state.",
    },
}


def _service(request: Request) -> EpisodeService:
    service: EpisodeService = request.app.state.episode_service
    return service


@router.get("/episodes", summary="The Board: episodes, newest first")
def get_episodes(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> EpisodeList:
    return _service(request).page(limit, offset)


@router.post(
    "/episodes",
    summary="Create an episode from an idea",
    status_code=201,
    responses=BAD_BODY_RESPONSE,
)
def post_episode(body: EpisodeCreate, request: Request) -> EpisodeDetail:
    return _service(request).create(body)


@router.get(
    "/episodes/{episode_id}", summary="One episode with its latest jobs", responses=NOT_FOUND
)
def get_episode(episode_id: uuid.UUID, request: Request) -> EpisodeDetail:
    return _service(request).get(episode_id)


@router.post(
    "/episodes/{episode_id}/advance",
    summary="Run the next state",
    responses={**NOT_FOUND, **CONFLICT},
)
def post_episode_advance(episode_id: uuid.UUID, request: Request) -> EpisodeDetail:
    return _service(request).advance(episode_id)


@router.post(
    "/episodes/{episode_id}/approve",
    summary="Pass the gate the episode waits at",
    responses={**NOT_FOUND, **CONFLICT},
)
def post_episode_approve(episode_id: uuid.UUID, request: Request) -> EpisodeDetail:
    return _service(request).approve(episode_id)


@router.post(
    "/episodes/{episode_id}/reject",
    summary="Turn down what is at the gate, with a comment",
    responses={**BAD_BODY_RESPONSE, **NOT_FOUND, **CONFLICT},
)
def post_episode_reject(
    episode_id: uuid.UUID, body: RejectRequest, request: Request
) -> EpisodeDetail:
    return _service(request).reject(episode_id, body)


@router.post(
    "/episodes/{episode_id}/rerun",
    summary="Run a state again. Later states become stale, nothing is deleted",
    responses={**BAD_BODY_RESPONSE, **NOT_FOUND, **CONFLICT},
)
def post_episode_rerun(
    episode_id: uuid.UUID, body: RerunRequest, request: Request
) -> EpisodeDetail:
    return _service(request).rerun(episode_id, body.state)


@router.get("/episodes/{episode_id}/spec", summary="The current authored spec", responses=NOT_FOUND)
def get_episode_spec(episode_id: uuid.UUID, request: Request) -> SpecOut:
    return _service(request).spec(episode_id)


@router.put(
    "/episodes/{episode_id}/spec",
    summary="Replace the authored spec. It is checked and stored as a new version",
    responses={**BAD_BODY_RESPONSE, **NOT_FOUND},
)
def put_episode_spec(episode_id: uuid.UUID, body: dict[str, Any], request: Request) -> SpecOut:
    return _service(request).replace_spec(episode_id, body)


@router.get(
    "/episodes/{episode_id}/spec/versions", summary="Every version of the spec", responses=NOT_FOUND
)
def get_episode_spec_versions(episode_id: uuid.UUID, request: Request) -> SpecVersions:
    return _service(request).versions(episode_id)


@router.get(
    "/episodes/{episode_id}/spec/diff",
    summary="What changed between two versions of the spec",
    responses=NOT_FOUND,
)
def get_episode_spec_diff(
    episode_id: uuid.UUID,
    request: Request,
    from_version: Annotated[int, Query(alias="from", ge=1, le=1_000_000)],
    to_version: Annotated[int, Query(alias="to", ge=1, le=1_000_000)],
) -> SpecDiff:
    return _service(request).diff(episode_id, from_version, to_version)


@router.post(
    "/episodes/{episode_id}/revise",
    summary="Ask for a change in words. Queues the revise skill and returns its job",
    status_code=202,
    responses={**BAD_BODY_RESPONSE, **NOT_FOUND},
)
def post_episode_revise(
    episode_id: uuid.UUID, body: ReviseRequest, request: Request
) -> RevisionOut:
    return _service(request).revise(episode_id, body.comment)


@router.get(
    "/episodes/{episode_id}/revisions/{job_id}",
    summary="A proposed revision: its patch and what it would change",
    responses=NOT_FOUND,
)
def get_episode_revision(episode_id: uuid.UUID, job_id: uuid.UUID, request: Request) -> RevisionOut:
    return _service(request).revision(episode_id, job_id)


@router.post(
    "/episodes/{episode_id}/revise/apply",
    summary="Apply a proposed revision. Stored as a new version of the spec",
    responses={**BAD_BODY_RESPONSE, **NOT_FOUND, **CONFLICT},
)
def post_episode_revise_apply(
    episode_id: uuid.UUID, body: ApplyRequest, request: Request
) -> SpecOut:
    return _service(request).apply(episode_id, body.job_id)
