"""Pipeline states and the jobs each one creates (design doc section 4.1).

A state has zero or more stages, and a stage is a set of jobs that may run side by side.
The next stage starts when every job of the current one has succeeded. Two states have two
stages: `asset_gen` makes images and then clips, `render` encodes scenes and then joins.

Three states are gates: after their jobs the episode waits for the owner.

This module is pure: it knows the rules, not the database. `packages/core/pipeline.py`
applies them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from packages.core.enums import EpisodeState, JobTag
from packages.core.stale import StaleScenes

STATES: tuple[EpisodeState, ...] = tuple(EpisodeState)

# The gate that follows a state, by the name the interface shows.
GATES: dict[EpisodeState, str] = {
    EpisodeState.DIRECTION: "plan",
    EpisodeState.ASSET_GEN: "assets",
    EpisodeState.CRITIQUE: "review",
}
# Section 4.2: a rejection returns by default to "the state that produced the gated
# output". The plan comes from direction, the assets from asset_gen, the video from render.
REJECT_RETURNS_TO: dict[EpisodeState, EpisodeState] = {
    EpisodeState.DIRECTION: EpisodeState.DIRECTION,
    EpisodeState.ASSET_GEN: EpisodeState.ASSET_GEN,
    EpisodeState.CRITIQUE: EpisodeState.RENDER,
}

# Director mode: one job plans a video. It reads the owner's prompt and writes the shot
# list (`plan.shotlist`, in the state `direction`, which the plan gate follows). The states
# `brief`, `script` and `asset_plan` of the first design keep their place in the order and
# have no job, so an episode passes over them.
RESEARCH_JOB = "plan.research"
# The planning states that no longer have a job. Running one of them again, for an
# episode that was started before Director mode, means running what follows it.
PASSED_OVER = (EpisodeState.BRIEF, EpisodeState.SCRIPT, EpisodeState.ASSET_PLAN)
_ONE_JOB: dict[EpisodeState, str] = {
    EpisodeState.DIRECTION: "plan.shotlist",
    EpisodeState.QC: "qc.run",
    EpisodeState.CRITIQUE: "agent.critic",
    EpisodeState.PACKAGE: "plan.package",
    EpisodeState.EXPORT: "export.pack",
}
_STAGES: dict[EpisodeState, int] = {
    **dict.fromkeys(_ONE_JOB, 1),
    # Research is a choice of the episode. It has its job only when the owner asked for it.
    EpisodeState.RESEARCH: 1,
    EpisodeState.ASSET_GEN: 2,
    EpisodeState.VOICE: 1,
    EpisodeState.RENDER: 2,
}

# The last state whose jobs have handlers. An episode rests after it instead of queuing a
# job that nothing can run. Quality checks and export arrive in milestone M4, the critic
# in M6. Move this forward as they are built, and set it to None when `done` is reachable.
LAST_BUILT_STATE: EpisodeState | None = EpisodeState.RENDER

# Which scenes to speak and to encode again. Empty means all of them.
Scope = StaleScenes


@dataclass(frozen=True)
class JobRequest:
    """A job the pipeline wants in the queue."""

    job_type: str
    tag: JobTag = JobTag.CPU
    payload: dict[str, Any] = field(default_factory=dict)


def index_of(state: EpisodeState) -> int:
    return STATES.index(state)


def next_state(state: EpisodeState) -> EpisodeState | None:
    """The state after this one, or None after the last."""
    position = index_of(state) + 1
    return STATES[position] if position < len(STATES) else None


def stage_count(state: EpisodeState) -> int:
    return _STAGES.get(state, 0)


def plan_stage(
    state: EpisodeState,
    stage: int,
    *,
    spec: Mapping[str, Any] | None,
    critic_enabled: bool = True,
    scope: Scope | None = None,
    research: bool = False,
) -> list[JobRequest]:
    """The jobs of one stage of a state. An empty list means the stage has nothing to do.

    `spec` is the episode's current authored spec, needed from `asset_gen` to `render`.
    `scope` limits voice and render to the scenes an edit made stale. `research` is the
    episode's own choice to have facts looked up before its plan is written.
    """
    if state is EpisodeState.CRITIQUE and not critic_enabled:
        return []
    if state is EpisodeState.RESEARCH:
        return [JobRequest(RESEARCH_JOB)] if research else []
    if state in _ONE_JOB:
        return [JobRequest(_ONE_JOB[state])]
    if state not in _STAGES:
        return []
    if spec is None:
        raise ValueError(f"The state '{state.value}' needs the episode's spec, and there is none.")

    scenes = spec["scenes"]
    if state is EpisodeState.ASSET_GEN:
        if stage == 0:
            return [
                JobRequest("gen.image", payload={"asset_id": asset["id"]})
                for asset in spec["assets"]
                if asset["kind"] == "image" and asset["origin"] == "generated"
            ]
        # One clip for each picture that a scene shows moving. A picture that two scenes
        # show gets one clip, named after the first of them.
        clips: dict[str, str] = {}
        for scene in scenes:
            visual = scene.get("visual", {})
            if visual.get("clip"):
                clips.setdefault(visual["asset_id"], scene["id"])
        return [
            JobRequest("gen.clip", JobTag.GPU, {"scene_id": scene_id, "asset_id": asset_id})
            for asset_id, scene_id in clips.items()
        ]
    if state is EpisodeState.VOICE:
        only = set(scope.voice) if scope and scope.voice else None
        return [
            JobRequest("gen.voice", payload={"scene_id": scene["id"]})
            for scene in scenes
            if scene["narration"].strip() and (only is None or scene["id"] in only)
        ]
    # Render: encode the scenes, then join them. The join always runs.
    if stage == 0:
        only = set(scope.render) if scope and scope.render else None
        return [
            JobRequest("render.scene", payload={"scene_id": scene["id"]})
            for scene in scenes
            if only is None or scene["id"] in only
        ]
    return [JobRequest("render.join")]
