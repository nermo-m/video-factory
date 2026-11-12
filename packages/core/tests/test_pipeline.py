"""The pipeline state machine on a real Postgres (design doc sections 4.1 and 4.2).

Every transition rule of section 4.2 has its tests here, under the rule it quotes.
Run with: make test-integration
"""

from __future__ import annotations

import copy
import json
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from packages.core import pipeline, queue, schemas
from packages.core.db import models
from packages.core.enums import (
    EpisodeState,
    ErrorClass,
    JobStatus,
    JobTag,
    SpecAuthor,
    SpecKind,
)
from packages.core.pipeline import PipelineError
from packages.core.stale import StaleScenes

pytestmark = pytest.mark.integration

S = EpisodeState


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    """Six scenes, one of them silent, one library picture, no clips."""
    path = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid" / "all_scene_kinds.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


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


# --- helpers ---------------------------------------------------------------------------


def episode(sessions: sessionmaker[Session], episode_id: uuid.UUID) -> models.Episode:
    with sessions() as session:
        found = session.get(models.Episode, episode_id)
        assert found is not None
        return found


def jobs(
    sessions: sessionmaker[Session],
    episode_id: uuid.UUID,
    *,
    status: JobStatus | None = None,
) -> list[models.Job]:
    with sessions() as session:
        query = (
            select(models.Job)
            .where(models.Job.episode_id == episode_id)
            .order_by(models.Job.created_at, models.Job.id)
        )
        if status is not None:
            query = query.where(models.Job.status == status)
        return list(session.scalars(query))


def queued(sessions: sessionmaker[Session], episode_id: uuid.UUID) -> list[str]:
    return sorted(job.type for job in jobs(sessions, episode_id, status=JobStatus.QUEUED))


def finish_one(sessions: sessionmaker[Session], tag: JobTag = JobTag.CPU) -> models.Job | None:
    """Do what the worker does for one job: claim it, store its result, tell the pipeline."""
    with sessions.begin() as session:
        claim = queue.claim_next(session, tag)
    if claim is None:
        return None
    with sessions.begin() as session:
        assert queue.complete(session, claim, {"ok": True})
        pipeline.job_succeeded(session, claim.id)
        job = session.get(models.Job, claim.id)
        assert job is not None
        return job


def give_spec(sessions: sessionmaker[Session], episode_id: uuid.UUID, body: dict[str, Any]) -> None:
    """Store an authored spec as the episode's current one, as the direction job will."""
    with sessions.begin() as session:
        latest = session.scalar(
            select(func.max(models.SpecVersion.version)).where(
                models.SpecVersion.episode_id == episode_id
            )
        )
        version = models.SpecVersion(
            episode_id=episode_id,
            version=(latest or 0) + 1,
            kind=SpecKind.AUTHORED,
            body=body,
            author=SpecAuthor.MODEL,
        )
        session.add(version)
        session.flush()
        found = session.get(models.Episode, episode_id)
        assert found is not None
        found.current_spec_id = version.id


def run_until(
    sessions: sessionmaker[Session],
    episode_id: uuid.UUID,
    stop: Callable[[models.Episode], bool],
    *,
    spec: dict[str, Any] | None = None,
) -> models.Episode:
    """Let the pipeline run, approving every gate, until `stop` says so."""
    with sessions.begin() as session:
        if session.get(models.Episode, episode_id).state is S.IDEA:  # type: ignore[union-attr]
            pipeline.advance(session, episode_id)
    for _ in range(200):
        current = episode(sessions, episode_id)
        if stop(current):
            return current
        if current.awaiting_approval:
            with sessions.begin() as session:
                pipeline.approve(session, episode_id)
            continue
        finished = finish_one(sessions) or finish_one(sessions, JobTag.GPU)
        assert finished is not None, f"the pipeline stopped at {current.state} with no job"
        if finished.type == "plan.direct" and spec is not None:
            give_spec(sessions, episode_id, spec)
    raise AssertionError("the pipeline did not reach the wanted point")


def at_gate(state: EpisodeState) -> Callable[[models.Episode], bool]:
    return lambda current: current.state is state and current.awaiting_approval


def in_state(state: EpisodeState) -> Callable[[models.Episode], bool]:
    return lambda current: current.state is state


# --- starting --------------------------------------------------------------------------


def test_a_new_episode_waits_at_idea_until_it_is_advanced(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    assert episode(sessions, episode_id).state is S.IDEA
    assert jobs(sessions, episode_id) == []

    with sessions.begin() as session:
        pipeline.advance(session, episode_id)

    assert episode(sessions, episode_id).state is S.BRIEF
    (job,) = jobs(sessions, episode_id)
    assert (job.type, job.tag, job.status) == ("plan.brief", JobTag.CPU, JobStatus.QUEUED)
    assert job.input["state"] == "brief"


def test_an_unknown_episode_is_an_error(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session, pytest.raises(PipelineError) as caught:
        pipeline.advance(session, uuid.uuid4())

    assert caught.value.code == "not_found"


# --- "A state advances only when all of its jobs have succeeded." ------------------------


def test_the_planning_states_follow_each_other_as_their_jobs_succeed(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)

    seen = []
    for _ in range(4):
        job = finish_one(sessions)
        assert job is not None
        seen.append(job.type)

    assert seen == ["plan.brief", "plan.research", "plan.script", "plan.direct"]
    assert episode(sessions, episode_id).state is S.DIRECTION


def test_a_state_with_several_jobs_waits_for_all_of_them(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, in_state(S.VOICE), spec=spec)
    spoken = [scene for scene in spec["scenes"] if scene["narration"]]
    assert queued(sessions, episode_id) == ["gen.voice"] * len(spoken)

    for _ in range(len(spoken) - 1):
        finish_one(sessions)
        assert episode(sessions, episode_id).state is S.VOICE

    finish_one(sessions)
    assert episode(sessions, episode_id).state is S.RENDER


def test_a_failed_job_holds_the_state(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)
    with sessions.begin() as session:
        claim = queue.claim_next(session, JobTag.CPU)
        assert claim is not None
        queue.fail(session, claim, ErrorClass.NEEDS_OWNER, "No API key.")

    assert episode(sessions, episode_id).state is S.BRIEF
    assert queued(sessions, episode_id) == []
    with sessions.begin() as session, pytest.raises(PipelineError) as caught:
        pipeline.advance(session, episode_id)
    assert caught.value.code == "jobs_unfinished"
    assert "1 failed" in str(caught.value)


def test_render_joins_only_after_every_scene_is_encoded(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, in_state(S.RENDER), spec=spec)
    assert queued(sessions, episode_id) == ["render.scene"] * len(spec["scenes"])

    for _ in range(len(spec["scenes"])):
        assert queued(sessions, episode_id).count("render.join") == 0
        finish_one(sessions)

    assert queued(sessions, episode_id) == ["render.join"]
    assert episode(sessions, episode_id).state is S.RENDER
    finish_one(sessions)
    assert episode(sessions, episode_id).state is S.QC


def test_a_stage_with_nothing_to_do_is_passed_over(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    # The fixture has a library picture and no clip, so asset_gen has no job at all and
    # the episode goes straight to its gate.
    run_until(sessions, episode_id, in_state(S.ASSET_GEN), spec=spec)

    current = episode(sessions, episode_id)
    assert current.awaiting_approval is True
    assert queued(sessions, episode_id) == []


def test_clips_are_generated_after_the_images_and_on_the_gpu_queue(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    with_clip = copy.deepcopy(spec)
    with_clip["assets"][0].update(origin="generated", prompt="a garden at dusk")
    with_clip["scenes"][1]["visual"]["clip"] = True
    run_until(sessions, episode_id, in_state(S.ASSET_GEN), spec=with_clip)

    assert queued(sessions, episode_id) == ["gen.image"]
    finish_one(sessions)

    (clip,) = jobs(sessions, episode_id, status=JobStatus.QUEUED)
    assert (clip.type, clip.tag) == ("gen.clip", JobTag.GPU)
    assert episode(sessions, episode_id).awaiting_approval is False
    finish_one(sessions, JobTag.GPU)
    assert episode(sessions, episode_id).awaiting_approval is True


def test_two_jobs_finishing_at_the_same_moment_advance_the_state_once(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, in_state(S.VOICE), spec=spec)
    claims = []
    with sessions.begin() as session:
        while (claim := queue.claim_next(session, JobTag.CPU)) is not None:
            claims.append(claim)
    together = threading.Barrier(len(claims))

    def finish(claim: queue.ClaimedJob) -> None:
        with sessions.begin() as session:
            queue.complete(session, claim, {})
            together.wait(timeout=10)
            pipeline.job_succeeded(session, claim.id)

    with ThreadPoolExecutor(len(claims)) as pool:
        list(pool.map(finish, claims))

    assert episode(sessions, episode_id).state is S.RENDER
    assert queued(sessions, episode_id) == ["render.scene"] * len(spec["scenes"])


def test_telling_the_pipeline_twice_about_a_job_changes_nothing(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)
    brief = finish_one(sessions)
    assert brief is not None

    with sessions.begin() as session:
        pipeline.job_succeeded(session, brief.id)

    assert episode(sessions, episode_id).state is S.RESEARCH
    assert [job.type for job in jobs(sessions, episode_id)] == ["plan.brief", "plan.research"]


def test_the_last_state_is_done_and_has_nothing_left_to_run(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    done = run_until(sessions, episode_id, in_state(S.DONE), spec=spec)

    assert done.awaiting_approval is False
    assert queued(sessions, episode_id) == []
    with sessions.begin() as session, pytest.raises(PipelineError) as caught:
        pipeline.advance(session, episode_id)
    assert caught.value.code == "finished"


# --- "A gate sets awaiting_approval=true. Approve advances." -----------------------------


def test_a_gate_holds_the_episode_until_the_owner_approves(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    current = run_until(sessions, episode_id, at_gate(S.DIRECTION), spec=spec)

    assert current.state is S.DIRECTION
    assert queued(sessions, episode_id) == []

    with sessions.begin() as session:
        pipeline.approve(session, episode_id)

    current = episode(sessions, episode_id)
    assert (current.state, current.awaiting_approval) == (S.ASSET_PLAN, False)
    assert queued(sessions, episode_id) == ["plan.assets"]


def test_an_episode_at_a_gate_cannot_be_advanced_past_it(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.DIRECTION), spec=spec)

    with sessions.begin() as session, pytest.raises(PipelineError) as caught:
        pipeline.advance(session, episode_id)

    assert caught.value.code == "awaiting_approval"
    assert episode(sessions, episode_id).state is S.DIRECTION


def test_only_an_episode_at_a_gate_can_be_approved_or_rejected(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)

    with sessions.begin() as session, pytest.raises(PipelineError) as approved:
        pipeline.approve(session, episode_id)
    with sessions.begin() as session, pytest.raises(PipelineError) as rejected:
        pipeline.reject(session, episode_id, comment="No.")

    assert approved.value.code == rejected.value.code == "not_awaiting_approval"


def test_the_three_gates_are_plan_assets_and_review(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    gates = []
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)
    for _ in range(200):
        current = episode(sessions, episode_id)
        if current.state is S.DONE:
            break
        if current.awaiting_approval:
            gates.append(current.state)
            with sessions.begin() as session:
                pipeline.approve(session, episode_id)
            continue
        finished = finish_one(sessions)
        assert finished is not None
        if finished.type == "plan.direct":
            give_spec(sessions, episode_id, spec)

    assert gates == [S.DIRECTION, S.ASSET_GEN, S.CRITIQUE]


def test_with_the_critic_switched_off_the_review_gate_follows_the_checks(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, in_state(S.QC), spec=spec)
    with sessions.begin() as session:
        claim = queue.claim_next(session, JobTag.CPU)
        assert claim is not None
        queue.complete(session, claim, {})
        pipeline.job_succeeded(session, claim.id, critic_enabled=False)

    current = episode(sessions, episode_id)
    assert (current.state, current.awaiting_approval) == (S.CRITIQUE, True)
    assert all(job.type != "agent.critic" for job in jobs(sessions, episode_id))


# --- "Reject requires a comment and returns to the state named in the reject action" -----


def test_a_rejection_needs_a_comment(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.DIRECTION), spec=spec)

    with sessions.begin() as session, pytest.raises(PipelineError) as caught:
        pipeline.reject(session, episode_id, comment="   ")

    assert caught.value.code == "comment_required"
    assert episode(sessions, episode_id).awaiting_approval is True


def test_a_rejected_plan_goes_back_to_direction_with_the_owners_comment(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.DIRECTION), spec=spec)

    with sessions.begin() as session:
        pipeline.reject(session, episode_id, comment="The hook is too slow.")

    current = episode(sessions, episode_id)
    assert (current.state, current.awaiting_approval) == (S.DIRECTION, False)
    (again,) = jobs(sessions, episode_id, status=JobStatus.QUEUED)
    assert again.type == "plan.direct"
    assert again.input["comment"] == "The hook is too slow."


def test_a_rejection_can_name_an_earlier_state_to_return_to(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.DIRECTION), spec=spec)

    with sessions.begin() as session:
        pipeline.reject(session, episode_id, comment="Wrong angle.", return_to_state=S.SCRIPT)

    current = episode(sessions, episode_id)
    assert (current.state, current.awaiting_approval) == (S.SCRIPT, False)
    assert current.stale_from_state is S.DIRECTION
    assert queued(sessions, episode_id) == ["plan.script"]


def test_a_rejected_video_goes_back_to_render_by_default(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.CRITIQUE), spec=spec)

    with sessions.begin() as session:
        pipeline.reject(session, episode_id, comment="The text is cut off.")

    current = episode(sessions, episode_id)
    assert current.state is S.RENDER
    assert current.stale_from_state is S.QC


def test_a_rejection_cannot_return_to_a_state_that_has_not_happened(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.DIRECTION), spec=spec)

    with sessions.begin() as session, pytest.raises(PipelineError) as caught:
        pipeline.reject(session, episode_id, comment="Skip ahead.", return_to_state=S.VOICE)

    assert caught.value.code == "invalid_state"


# --- "Any state can be re-run. Re-running a state marks all later states stale but
# deletes nothing." ---------------------------------------------------------------------


def test_an_earlier_state_can_be_run_again_and_nothing_is_deleted(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, in_state(S.VOICE), spec=spec)
    before = jobs(sessions, episode_id)

    with sessions.begin() as session:
        pipeline.rerun(session, episode_id, S.SCRIPT)

    current = episode(sessions, episode_id)
    assert (current.state, current.awaiting_approval) == (S.SCRIPT, False)
    assert current.stale_from_state is S.DIRECTION
    after = jobs(sessions, episode_id)
    assert {job.id for job in before} < {job.id for job in after}
    earlier_results = {job.id: job.output for job in before if job.status is JobStatus.SUCCEEDED}
    assert earlier_results
    for job in after:
        if job.id in earlier_results:
            assert (job.status, job.output) == (JobStatus.SUCCEEDED, earlier_results[job.id])
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(models.SpecVersion)) == 1


def test_the_current_state_can_be_run_again_without_marking_anything_stale(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)
    finish_one(sessions)

    with sessions.begin() as session:
        pipeline.rerun(session, episode_id, S.RESEARCH)

    current = episode(sessions, episode_id)
    assert current.state is S.RESEARCH
    assert current.stale_from_state is None
    assert queued(sessions, episode_id) == ["plan.research"]


def test_a_re_run_from_a_gate_clears_the_gate(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.DIRECTION), spec=spec)

    with sessions.begin() as session:
        pipeline.rerun(session, episode_id, S.BRIEF)

    current = episode(sessions, episode_id)
    assert (current.state, current.awaiting_approval) == (S.BRIEF, False)


@pytest.mark.parametrize("state", [S.RENDER, S.IDEA, S.DONE])
def test_a_state_that_was_never_reached_or_has_no_jobs_cannot_be_re_run(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, state: EpisodeState
) -> None:
    with sessions.begin() as session:
        pipeline.advance(session, episode_id)

    with sessions.begin() as session, pytest.raises(PipelineError) as caught:
        pipeline.rerun(session, episode_id, state)

    assert caught.value.code == "invalid_state"


def test_a_re_run_cancels_what_was_still_waiting_and_ignores_late_results(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, in_state(S.VOICE), spec=spec)
    with sessions.begin() as session:
        in_flight = queue.claim_next(session, JobTag.CPU)
        assert in_flight is not None

    with sessions.begin() as session:
        pipeline.rerun(session, episode_id, S.SCRIPT)

    statuses = {job.status for job in jobs(sessions, episode_id) if job.type == "gen.voice"}
    assert statuses == {JobStatus.CANCELLED}
    # The worker that was half way through a voice job reports back. Too late.
    with sessions.begin() as session:
        assert queue.complete(session, in_flight, {}) is False
        pipeline.job_succeeded(session, in_flight.id)
    assert episode(sessions, episode_id).state is S.SCRIPT
    assert queued(sessions, episode_id) == ["plan.script"]


def test_the_stale_marker_moves_forward_as_the_states_are_done_again(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, in_state(S.VOICE), spec=spec)
    with sessions.begin() as session:
        pipeline.rerun(session, episode_id, S.SCRIPT)
    assert episode(sessions, episode_id).stale_from_state is S.DIRECTION

    finish_one(sessions)  # script again
    assert episode(sessions, episode_id).stale_from_state is S.DIRECTION
    finish_one(sessions)  # direction again: now it is the asset plan that is out of date
    assert episode(sessions, episode_id).stale_from_state is S.ASSET_PLAN

    back_at_voice = run_until(sessions, episode_id, in_state(S.VOICE), spec=spec)
    # Voice had not finished before the re-run, so nothing after asset_gen is stale.
    assert back_at_voice.stale_from_state is None


# --- "Editing the spec after plan approval marks only the affected scenes stale." --------


def edited(spec: dict[str, Any], **changes: Any) -> dict[str, Any]:
    new = copy.deepcopy(spec)
    new["scenes"][1].update(changes)
    return new


def test_an_edit_before_the_plan_is_approved_makes_nothing_stale(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.DIRECTION), spec=spec)

    with sessions.begin() as session:
        stale = pipeline.spec_edited(
            session, episode_id, spec, edited(spec, narration="She watered two rows.")
        )

    assert stale == StaleScenes()
    current = episode(sessions, episode_id)
    assert current.stale_scenes == {}
    assert current.stale_from_state is None


def test_changed_narration_marks_voice_and_render_of_that_scene_only(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.CRITIQUE), spec=spec)
    new = edited(spec, narration="She watered two rows before work.")
    give_spec(sessions, episode_id, new)

    with sessions.begin() as session:
        stale = pipeline.spec_edited(session, episode_id, spec, new)

    assert stale == StaleScenes(voice=("s02_story",), render=("s02_story",))
    current = episode(sessions, episode_id)
    assert current.stale_scenes == {"voice": ["s02_story"], "render": ["s02_story"]}
    assert current.stale_from_state is S.VOICE
    # Marking is all an edit does. Nothing runs until the owner asks for it.
    assert (current.state, current.awaiting_approval) == (S.CRITIQUE, True)
    assert queued(sessions, episode_id) == []


def test_only_the_stale_scene_is_spoken_and_encoded_again(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.CRITIQUE), spec=spec)
    new = edited(spec, narration="She watered two rows before work.")
    give_spec(sessions, episode_id, new)
    with sessions.begin() as session:
        pipeline.spec_edited(session, episode_id, spec, new)

    with sessions.begin() as session:
        pipeline.rerun(session, episode_id, S.VOICE)

    (voice,) = jobs(sessions, episode_id, status=JobStatus.QUEUED)
    assert (voice.type, voice.input["scene_id"]) == ("gen.voice", "s02_story")
    finish_one(sessions)
    (scene,) = jobs(sessions, episode_id, status=JobStatus.QUEUED)
    assert (scene.type, scene.input["scene_id"]) == ("render.scene", "s02_story")
    finish_one(sessions)
    assert queued(sessions, episode_id) == ["render.join"]
    finish_one(sessions)

    current = episode(sessions, episode_id)
    assert current.state is S.QC
    assert current.stale_scenes == {}


def test_a_changed_visual_marks_render_only_and_voice_is_left_alone(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.CRITIQUE), spec=spec)
    new = edited(spec, title="THE ORCHARD")
    give_spec(sessions, episode_id, new)

    with sessions.begin() as session:
        pipeline.spec_edited(session, episode_id, spec, new)

    current = episode(sessions, episode_id)
    assert current.stale_scenes == {"voice": [], "render": ["s02_story"]}
    assert current.stale_from_state is S.RENDER


def test_changed_timing_marks_render_of_that_scene_and_every_later_one(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.CRITIQUE), spec=spec)
    new = edited(spec, pad_after_s=1.5)
    give_spec(sessions, episode_id, new)

    with sessions.begin() as session:
        pipeline.spec_edited(session, episode_id, spec, new)
    with sessions.begin() as session:
        pipeline.rerun(session, episode_id, S.RENDER)

    later = [scene["id"] for scene in spec["scenes"][1:]]
    assert episode(sessions, episode_id).stale_scenes == {"voice": [], "render": later}
    again = jobs(sessions, episode_id, status=JobStatus.QUEUED)
    assert sorted(job.input["scene_id"] for job in again) == sorted(later)
    assert {job.type for job in again} == {"render.scene"}


def test_two_edits_in_a_row_add_up(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    run_until(sessions, episode_id, at_gate(S.CRITIQUE), spec=spec)
    first = edited(spec, title="THE ORCHARD")
    second = copy.deepcopy(first)
    second["scenes"][3]["narration"] = "Pick it. Shrink it. Repeat it daily."

    with sessions.begin() as session:
        pipeline.spec_edited(session, episode_id, spec, first)
        pipeline.spec_edited(session, episode_id, first, second)

    assert episode(sessions, episode_id).stale_scenes == {
        "voice": ["s04_steps"],
        "render": ["s02_story", "s04_steps"],
    }


def test_an_edit_while_the_voice_has_not_been_made_yet_marks_nothing(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    # After plan approval, but nothing has been spoken or rendered: there is nothing to
    # be stale, and the states ahead will use the edited spec anyway.
    run_until(sessions, episode_id, in_state(S.ASSET_PLAN), spec=spec)

    with sessions.begin() as session:
        pipeline.spec_edited(
            session, episode_id, spec, edited(spec, narration="She watered two rows.")
        )

    current = episode(sessions, episode_id)
    assert current.stale_scenes == {}
    assert current.stale_from_state is None


def test_re_running_a_state_before_voice_drops_the_scene_marks(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    # Everything from that state on is made again in full, so a list of single stale
    # scenes would only make the voice and render states skip scenes they must redo.
    run_until(sessions, episode_id, at_gate(S.CRITIQUE), spec=spec)
    new = edited(spec, narration="She watered two rows before work.")
    with sessions.begin() as session:
        pipeline.spec_edited(session, episode_id, spec, new)

    with sessions.begin() as session:
        pipeline.rerun(session, episode_id, S.DIRECTION)

    assert episode(sessions, episode_id).stale_scenes == {}
