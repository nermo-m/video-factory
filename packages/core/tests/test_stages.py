"""Pipeline states and the jobs each one creates (design doc section 4.1). Pure rules."""

from __future__ import annotations

import json
from typing import Any

import pytest

from packages.core import schemas
from packages.core.enums import EpisodeState, JobTag
from packages.core.stages import (
    GATES,
    LAST_BUILT_STATE,
    REJECT_RETURNS_TO,
    Scope,
    next_state,
    plan_stage,
    stage_count,
)

SINGLE_JOB_STATES = {
    EpisodeState.BRIEF: "plan.brief",
    EpisodeState.RESEARCH: "plan.research",
    EpisodeState.SCRIPT: "plan.script",
    EpisodeState.DIRECTION: "plan.direct",
    EpisodeState.ASSET_PLAN: "plan.assets",
    EpisodeState.QC: "qc.run",
    EpisodeState.PACKAGE: "plan.package",
    EpisodeState.EXPORT: "export.pack",
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    """The all-scene-kinds fixture: six scenes, one of them silent, one picture."""
    path = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid" / "all_scene_kinds.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_the_states_follow_each_other_in_the_order_of_the_design() -> None:
    order = [EpisodeState.IDEA]
    while (following := next_state(order[-1])) is not None:
        order.append(following)

    assert [state.value for state in order] == [
        "idea",
        "brief",
        "research",
        "script",
        "direction",
        "asset_plan",
        "asset_gen",
        "voice",
        "render",
        "qc",
        "critique",
        "package",
        "export",
        "done",
    ]


def test_the_three_gates_are_plan_assets_and_review() -> None:
    assert GATES == {
        EpisodeState.DIRECTION: "plan",
        EpisodeState.ASSET_GEN: "assets",
        EpisodeState.CRITIQUE: "review",
    }


def test_a_rejection_returns_to_the_state_that_produced_what_was_rejected() -> None:
    # The plan comes from direction, the assets from asset_gen, the video from render.
    assert REJECT_RETURNS_TO == {
        EpisodeState.DIRECTION: EpisodeState.DIRECTION,
        EpisodeState.ASSET_GEN: EpisodeState.ASSET_GEN,
        EpisodeState.CRITIQUE: EpisodeState.RENDER,
    }


@pytest.mark.parametrize(("state", "job_type"), sorted(SINGLE_JOB_STATES.items()))
def test_a_planning_state_creates_its_one_cpu_job(state: EpisodeState, job_type: str) -> None:
    assert stage_count(state) == 1

    (job,) = plan_stage(state, 0, spec=None)

    assert (job.job_type, job.tag, job.payload) == (job_type, JobTag.CPU, {})


@pytest.mark.parametrize("state", [EpisodeState.IDEA, EpisodeState.DONE])
def test_idea_and_done_create_no_jobs(state: EpisodeState) -> None:
    assert stage_count(state) == 0


def test_voice_creates_one_job_per_scene_that_speaks(spec: dict[str, Any]) -> None:
    jobs = plan_stage(EpisodeState.VOICE, 0, spec=spec)

    spoken = [scene["id"] for scene in spec["scenes"] if scene["narration"]]
    assert [job.payload for job in jobs] == [{"scene_id": scene_id} for scene_id in spoken]
    assert {job.job_type for job in jobs} == {"gen.voice"}
    assert len(spoken) == len(spec["scenes"]) - 1


def test_render_encodes_every_scene_and_then_joins(spec: dict[str, Any]) -> None:
    assert stage_count(EpisodeState.RENDER) == 2

    scenes = plan_stage(EpisodeState.RENDER, 0, spec=spec)
    join = plan_stage(EpisodeState.RENDER, 1, spec=spec)

    assert [job.payload["scene_id"] for job in scenes] == [scene["id"] for scene in spec["scenes"]]
    assert {job.job_type for job in scenes} == {"render.scene"}
    assert [(job.job_type, job.tag) for job in join] == [("render.join", JobTag.CPU)]


def test_asset_gen_makes_images_first_and_then_clips_on_the_gpu(spec: dict[str, Any]) -> None:
    with_clip = json.loads(json.dumps(spec))
    with_clip["assets"][0]["origin"] = "generated"
    with_clip["assets"][0]["prompt"] = "a garden at dusk"
    with_clip["scenes"][1]["visual"]["clip"] = True

    images = plan_stage(EpisodeState.ASSET_GEN, 0, spec=with_clip)
    clips = plan_stage(EpisodeState.ASSET_GEN, 1, spec=with_clip)

    assert [(job.job_type, job.tag, job.payload) for job in images] == [
        ("gen.image", JobTag.CPU, {"asset_id": "a_garden_dusk"})
    ]
    assert [(job.job_type, job.tag, job.payload) for job in clips] == [
        ("gen.clip", JobTag.GPU, {"scene_id": "s02_story", "asset_id": "a_garden_dusk"})
    ]


def test_uploaded_and_library_pictures_need_no_image_job(spec: dict[str, Any]) -> None:
    # The fixture's only asset comes from the library, and no scene asks for a clip.
    assert plan_stage(EpisodeState.ASSET_GEN, 0, spec=spec) == []
    assert plan_stage(EpisodeState.ASSET_GEN, 1, spec=spec) == []


def test_critique_runs_the_critic_only_when_it_is_switched_on() -> None:
    (job,) = plan_stage(EpisodeState.CRITIQUE, 0, spec=None, critic_enabled=True)

    assert job.job_type == "agent.critic"
    assert plan_stage(EpisodeState.CRITIQUE, 0, spec=None, critic_enabled=False) == []


def test_only_stale_scenes_are_spoken_and_encoded_again(spec: dict[str, Any]) -> None:
    scope = Scope(voice=("s02_story",), render=("s02_story", "s03_fact"))

    voice = plan_stage(EpisodeState.VOICE, 0, spec=spec, scope=scope)
    scenes = plan_stage(EpisodeState.RENDER, 0, spec=spec, scope=scope)
    join = plan_stage(EpisodeState.RENDER, 1, spec=spec, scope=scope)

    assert [job.payload["scene_id"] for job in voice] == ["s02_story"]
    assert [job.payload["scene_id"] for job in scenes] == ["s02_story", "s03_fact"]
    # The video is always joined again.
    assert len(join) == 1


def test_a_state_that_needs_the_spec_says_so_when_there_is_none() -> None:
    with pytest.raises(ValueError, match="spec"):
        plan_stage(EpisodeState.VOICE, 0, spec=None)


def test_the_built_pipeline_ends_with_the_render() -> None:
    """Milestone M2 builds the pipeline up to the render. An episode rests there."""
    assert LAST_BUILT_STATE is EpisodeState.RENDER
