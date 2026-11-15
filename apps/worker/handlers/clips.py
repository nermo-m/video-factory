"""The job that makes a picture move: `gen.clip` (design doc sections 4.1 and 8, FR-07).

One job makes the clip of one picture, with the open video model on the owner's graphics
card. The clip starts from the stored picture and follows the scene's words about its
motion, the scene's camera move and the look of the video.

The model makes about five seconds at a time. A longer scene is made in pieces: each piece
starts from the last frame of the one before, and FFmpeg joins them. The length aimed for
is the scene's expected length, because the voice is spoken after the pictures are made.

A clip that is there is kept. It is made again when the job says `regenerate`, when the
words about its motion were rewritten, when it has become too short for its scene, or when
its picture is new: a clip belongs to the version of the picture it was made from.

Demo mode has no graphics card job. The scene then shows its still picture.
"""

from __future__ import annotations

import contextlib
import math
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers.plan import current_spec
from apps.worker.runner import Handler, JobContext
from packages.adapters.clip import CLIP_FPS, MAX_FRAMES, ClipAdapter, ClipRequest, wan_frames
from packages.core import assets, lengths, pipeline, prompts
from packages.core.db.models import AssetVersion, Channel, Episode, Job
from packages.core.enums import ErrorClass, JobStatus
from packages.core.queue import JobError, NeedsOwnerError
from packages.core.storage import StorageAdapter

CLIP_JOB = "gen.clip"
# A clip is made a little longer than its scene is expected to be, because the spoken
# line may take longer than its estimate.
SPARE = 1.1
# A scene longer than three pieces holds its last frame for the rest.
MAX_PIECES = 3
# Wan 2.2 at its small size, upright. The render scales it to the frame.
SIZE = (480, 832)
# A clip that is this much shorter than its scene needs is made again.
SHORT_BY_S = 0.5

# Joins the pieces of a clip into one file: (data folder, pieces, target).
Joiner = Callable[[Path, list[Path], Path], None]


def pieces_for(seconds: float) -> list[int]:
    """The frame counts of the pieces of a clip that is at least this long.

    The first frame of a later piece is the last frame of the one before, so a later
    piece adds one frame less than it holds.
    """
    wanted = math.ceil(seconds * CLIP_FPS - 1e-9)
    pieces: list[int] = []
    have = 0
    while have < wanted and len(pieces) < MAX_PIECES:
        missing = wanted - have + (1 if pieces else 0)
        frames = wan_frames(missing / CLIP_FPS)
        pieces.append(frames)
        have += frames - (1 if len(pieces) > 1 else 0)
    return pieces or [wan_frames(0)]


def _seconds_of(pieces: list[int]) -> float:
    return (sum(pieces) - (len(pieces) - 1)) / CLIP_FPS


def _text(context: JobContext, name: str) -> str:
    value = context.job.input.get(name)
    if not isinstance(value, str) or not value:
        raise JobError(f"A '{CLIP_JOB}' job needs {name}.", error_class=ErrorClass.BUG)
    return value


def _episode(session: Session, episode_id: uuid.UUID | None) -> tuple[Episode, Channel]:
    episode = session.get(Episode, episode_id) if episode_id is not None else None
    if episode is None:
        raise JobError("A clip job needs an episode.", error_class=ErrorClass.BUG)
    channel = session.get(Channel, episode.channel_id)
    assert channel is not None  # noqa: S101 - the foreign key guarantees it
    return episode, channel


def clip_handlers(
    sessions: sessionmaker[Session],
    *,
    storage: StorageAdapter,
    data_dir: Path,
    clips: Callable[[], ClipAdapter | None],
    join: Joiner,
    size: tuple[int, int] = SIZE,
) -> dict[str, Handler]:
    """The handler, for a worker that has a database, a data folder and a clip adapter.

    `clips` is called for every job and answers None in a mode without a graphics card
    job. `join` is FFmpeg in the worker and is replaced in tests that run without it.
    """

    def gen_clip(context: JobContext) -> Mapping[str, Any]:
        asset_id, scene_id = _text(context, "asset_id"), _text(context, "scene_id")
        said = {"asset_id": asset_id, "scene_id": scene_id}
        with sessions.begin() as session:
            episode, channel = _episode(session, context.job.episode_id)
            spec = current_spec(session, episode)
            moving = [
                scene
                for scene in spec["scenes"]
                if scene.get("visual", {}).get("asset_id") == asset_id
                and scene["visual"].get("clip")
            ]
            if not moving:
                return {
                    **said,
                    "made": False,
                    "why": "This picture is not asked to move: its scene's clip is off.",
                }
            adapter = clips()
            if adapter is None:
                return {
                    **said,
                    "made": False,
                    "why": "This mode has no graphics card job, so no clip is made. The "
                    "scene shows its still picture with its camera move.",
                }
            picture = next(
                (item for item in assets.resolve(session, episode, spec) if item.id == asset_id),
                None,
            )
            if picture is None or picture.version is None or picture.file is None:
                raise NeedsOwnerError(
                    f"The scene '{scene_id}' has no picture yet, so there is nothing to "
                    "move. Make or upload its picture, then run the pictures step again."
                )
            scene = next((item for item in moving if item["id"] == scene_id), moving[0])
            prompt = prompts.motion(spec, scene)
            # Long enough for every scene that shows this picture moving.
            wanted_s = max(lengths.estimate(item, channel.voice_speed) for item in moving) * SPARE
            pieces = pieces_for(wanted_s)
            version = picture.version
            again = bool(context.job.input.get("regenerate"))
            has = version.clip_path is not None
            long_enough = (version.clip_s or 0) + SHORT_BY_S >= min(
                wanted_s, MAX_PIECES * MAX_FRAMES / CLIP_FPS
            )
            if has and not again and version.clip_prompt == prompt and long_enough:
                return {
                    **said,
                    "made": False,
                    "file": version.clip_path,
                    "why": "This picture already has its clip. Make clip again makes a new one.",
                }
            start = storage.read_bytes(picture.file)
            version_id = version.id
            # A clip that is made again moves differently: its seed follows the job.
            seed = (int(spec.get("seed") or 0) * 1009 + context.job.id.int) % (2**48)

        made: list[Path] = []
        latency_ms = 0
        model = ""
        for number, frames in enumerate(pieces):
            result = adapter.create(
                ClipRequest(
                    name=f"{asset_id}_{number}",
                    picture=start,
                    prompt=prompt,
                    frames=frames,
                    seed=seed + number,
                    width=size[0],
                    height=size[1],
                )
            )
            stored = context.output_path / (
                f"{asset_id}.mp4" if len(pieces) == 1 else f"{asset_id}.{number}.mp4"
            )
            storage.write_bytes(stored, result.video)
            made.append(data_dir / stored)
            start = result.last_frame
            latency_ms += result.latency_ms
            model = result.model

        target = context.output_path / f"{asset_id}.mp4"
        if len(made) > 1:
            join(data_dir, made, data_dir / target)
        seconds = _seconds_of(pieces)

        with sessions.begin() as session:
            episode, _channel = _episode(session, context.job.episode_id)
            stored_version = session.get(AssetVersion, version_id)
            assert stored_version is not None  # noqa: S101 - read above
            assets.set_clip(
                session,
                stored_version,
                file_path=target.as_posix(),
                prompt=prompt,
                model=model,
                seconds=seconds,
            )
            # A video that already shows this picture is out of date now (section 4.2).
            pipeline.asset_changed(session, episode.id, asset_id)
            waiting = session.scalar(
                select(Job.id)
                .where(
                    Job.type == CLIP_JOB,
                    Job.status == JobStatus.QUEUED,
                    Job.id != context.job.id,
                )
                .limit(1)
            )
        if waiting is None:
            # Nothing else needs the card: give its memory back (section 8, step 7).
            # The clip is made and stored. A card that keeps its memory a little longer
            # is not a reason to fail the job.
            with contextlib.suppress(JobError, OSError):
                adapter.release()

        return {
            **said,
            "made": True,
            "file": target.as_posix(),
            "seconds": seconds,
            "pieces": len(pieces),
            "width": size[0],
            "height": size[1],
            "model": model,
            "latency_ms": latency_ms,
        }

    return {CLIP_JOB: gen_clip}
