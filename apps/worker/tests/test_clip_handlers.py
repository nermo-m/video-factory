"""The clip job on a real Postgres (design doc sections 4.1 and 8, FR-07).

A stand-in for the clip adapter remembers what it was asked. No graphics card is used.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers.clips import CLIP_JOB, clip_handlers, pieces_for
from apps.worker.runner import JobContext
from packages.adapters.clip import ClipRequest, ClipResult
from packages.adapters.storage import LocalStorage
from packages.core import assets, queue
from packages.core.db import models
from packages.core.enums import EpisodeState, JobTag, SpecAuthor
from packages.core.queue import NeedsOwnerError
from packages.core.specs import store_spec

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
PNG = (ROOT / "samples/lighthouse_keeper/assets/a_storm_sea.png").read_bytes()
SHOTS: dict[str, Any] = json.loads(
    (ROOT / "schemas/fixtures/episode_spec/valid/shots.json").read_text(encoding="utf-8")
)
STYLE = SHOTS["style"]
MOTION = SHOTS["scenes"][0]["visual"]["motion"]


class FakeClips:
    """A clip adapter that remembers what it was asked."""

    def __init__(self, error: Exception | None = None) -> None:
        self.requests: list[ClipRequest] = []
        self.released = 0
        self.error = error

    def create(self, request: ClipRequest) -> ClipResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        number = len(self.requests)
        return ClipResult(
            video=b"video %d" % number,
            last_frame=b"last frame %d" % number,
            frames=request.frames,
            fps=16.0,
            width=request.width,
            height=request.height,
            model="wan test",
            latency_ms=1000,
        )

    def release(self) -> None:
        self.released += 1


def joined(data_dir: Path, pieces: list[Path], target: Path) -> None:
    """Stands in for FFmpeg: the pieces one after the other."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b" + ".join(piece.read_bytes() for piece in pieces))


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


def new_episode(sessions: sessionmaker[Session], spec: dict[str, Any]) -> uuid.UUID:
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="night_scrolls")
        session.add(channel)
        session.flush()
        episode = models.Episode(
            channel_id=channel.id, idea="A keeper.", state=EpisodeState.ASSET_GEN
        )
        session.add(episode)
        session.flush()
        store_spec(session, episode.id, spec, author=SpecAuthor.MODEL)
        assets.sync(session, episode, spec, manifest={})
        return episode.id


def give_picture(
    sessions: sessionmaker[Session], data_dir: Path, episode_id: uuid.UUID, asset_id: str
) -> str:
    """Store a picture for an asset, as the picture job would."""
    stored = f"episodes/{episode_id}/pictures/{uuid.uuid4().hex}/{asset_id}.png"
    LocalStorage(data_dir).write_bytes(stored, PNG)
    with sessions.begin() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        picture = now(session, episode, asset_id)
        assert picture.asset is not None
        assets.add_version(session, picture.asset, file_path=stored)
    return stored


def now(session: Session, episode: models.Episode, asset_id: str) -> assets.Picture:
    from apps.worker.handlers.plan import current_spec

    spec = current_spec(session, episode)
    return next(item for item in assets.resolve(session, episode, spec) if item.id == asset_id)


def picture(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, asset_id: str
) -> assets.Picture:
    with sessions() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        return now(session, episode, asset_id)


class Stage:
    def __init__(self, sessions: sessionmaker[Session], data_dir: Path, clips: Any) -> None:
        self.sessions = sessions
        self.data_dir = data_dir
        self.clips = clips
        self.handlers = clip_handlers(
            sessions,
            storage=LocalStorage(data_dir),
            data_dir=data_dir,
            clips=lambda: self.clips,
            join=joined,
        )

    def run(self, episode_id: uuid.UUID, **payload: Any) -> dict[str, Any]:
        with self.sessions.begin() as session:
            queue.enqueue(
                session,
                job_type=CLIP_JOB,
                tag=JobTag.GPU,
                payload=payload,
                episode_id=episode_id,
            )
        with self.sessions.begin() as session:
            claim = queue.claim_next(session, JobTag.GPU)
        assert claim is not None
        output = dict(self.handlers[CLIP_JOB](JobContext(claim, queue.output_path_of(claim))) or {})
        with self.sessions.begin() as session:
            queue.complete(session, claim, output)
        return output


@pytest.fixture
def stage(sessions: sessionmaker[Session], tmp_path: Path) -> Stage:
    return Stage(sessions, tmp_path / "data", FakeClips())


def test_fr07_a_picture_becomes_a_clip_that_is_stored_with_it(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    episode_id = new_episode(sessions, SHOTS)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")

    output = stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    made = picture(sessions, episode_id, "a_s01_hill")
    assert output["made"] is True
    assert output["file"].startswith(f"episodes/{episode_id}/jobs/gen.clip/")
    assert output["file"].endswith("/a_s01_hill.mp4")
    assert (stage.data_dir / output["file"]).read_bytes() == b"video 1"
    assert made.clip == output["file"]
    assert made.version is not None
    assert (made.version.clip_model, made.version.clip_s) == ("wan test", output["seconds"])
    # The start picture is the stored one, and the words are the scene's motion, the
    # camera move and the look of the video.
    asked = stage.clips.requests[0]
    assert asked.picture == PNG
    assert asked.prompt == f"{MOTION} The camera slowly pushes in. {STYLE}"
    assert made.version.clip_prompt == asked.prompt
    assert (asked.width, asked.height) == (480, 832)


def test_a_clip_is_as_long_as_its_scene_is_expected_to_be(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    episode_id = new_episode(sessions, SHOTS)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")

    output = stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    # Seven words at 2.3 a second and the pause after a scene, with a tenth to spare.
    assert [request.frames for request in stage.clips.requests] == [69]
    assert output["seconds"] == pytest.approx(69 / 16)
    assert output["pieces"] == 1


def test_a_long_scene_is_made_in_pieces_and_each_starts_where_the_last_one_ended(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    spec = copy.deepcopy(SHOTS)
    spec["scenes"][0]["narration"] = " ".join(["word"] * 22)
    episode_id = new_episode(sessions, spec)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")

    output = stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    first, second, third = stage.clips.requests
    assert (first.frames, second.frames, third.frames) == (81, 81, 21)
    assert (first.picture, second.picture, third.picture) == (PNG, b"last frame 1", b"last frame 2")
    # Every piece has its own seed, and all of them the same words.
    assert len({first.seed, second.seed, third.seed}) == 3
    assert first.prompt == second.prompt == third.prompt
    assert output["pieces"] == 3
    assert (stage.data_dir / output["file"]).read_bytes() == b"video 1 + video 2 + video 3"
    # The first frame of a later piece is the last frame of the one before, shown once.
    assert output["seconds"] == pytest.approx((81 + 80 + 20) / 16)


@pytest.mark.parametrize(
    ("seconds", "pieces"),
    [
        (1.0, [17]),
        (5.0, [81]),
        (5.2, [81, 17]),
        (9.0, [81, 65]),
        (14.9, [81, 81, 81]),
        # Three pieces are the most: a scene longer than that holds its last frame.
        (40.0, [81, 81, 81]),
    ],
)
def test_the_pieces_of_a_clip(seconds: float, pieces: list[int]) -> None:
    assert pieces_for(seconds) == pieces


def test_a_clip_that_is_there_is_kept_and_made_again_only_when_asked(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    episode_id = new_episode(sessions, SHOTS)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")
    first = stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    kept = stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")
    again = stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill", regenerate=True)

    assert (kept["made"], kept["file"]) == (False, first["file"])
    assert "already has its clip" in kept["why"]
    assert again["made"] is True
    assert again["file"] != first["file"]
    assert len(stage.clips.requests) == 2
    # Made again, it moves differently.
    assert stage.clips.requests[0].seed != stage.clips.requests[1].seed
    assert picture(sessions, episode_id, "a_s01_hill").clip == again["file"]


def test_a_clip_is_made_again_when_the_motion_was_rewritten_or_the_picture_is_new(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    episode_id = new_episode(sessions, SHOTS)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")
    stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    edited = copy.deepcopy(SHOTS)
    edited["scenes"][0]["visual"]["motion"] = "She stops and looks at the sea."
    with sessions.begin() as session:
        store_spec(session, episode_id, edited, author=SpecAuthor.OWNER)
    rewritten = stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")
    new_picture = stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    assert (rewritten["made"], new_picture["made"]) == (True, True)
    assert stage.clips.requests[1].prompt.startswith("She stops and looks at the sea.")


def test_a_video_that_shows_the_picture_is_out_of_date_once_it_moves(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    episode_id = new_episode(sessions, SHOTS)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")
    with sessions.begin() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        episode.state = EpisodeState.RENDER
        episode.stale_from_state = None
        episode.stale_scenes = {}
        # The video was rendered once.
        queue.enqueue(
            session,
            job_type="render.join",
            tag=JobTag.CPU,
            payload={"state": "render", "run": 1, "stage": 1},
            episode_id=episode_id,
        )
    with sessions.begin() as session:
        rendered = queue.claim_next(session, JobTag.CPU)
        assert rendered is not None
        queue.complete(session, rendered, {})

    stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill", regenerate=True)

    with sessions() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        assert episode.stale_scenes.get("render") == ["s01_hill"]


def test_a_picture_that_is_not_made_yet_cannot_move(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    episode_id = new_episode(sessions, SHOTS)

    with pytest.raises(NeedsOwnerError, match="has no picture yet"):
        stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    assert stage.clips.requests == []


def test_a_scene_the_owner_switched_to_still_gets_no_clip(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    episode_id = new_episode(sessions, SHOTS)
    give_picture(sessions, stage.data_dir, episode_id, "a_s02_lamp")

    output = stage.run(episode_id, asset_id="a_s02_lamp", scene_id="s02_lamp")

    assert output["made"] is False
    assert "not asked to move" in output["why"]
    assert stage.clips.requests == []


def test_without_a_graphics_card_job_the_scene_shows_its_still_picture(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    # Demo mode has no clip adapter.
    stage = Stage(sessions, tmp_path / "data", None)
    episode_id = new_episode(sessions, SHOTS)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")

    output = stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    assert output["made"] is False
    assert "still picture" in output["why"]
    assert picture(sessions, episode_id, "a_s01_hill").clip is None


def test_the_card_is_given_back_after_the_last_clip_that_waits(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    spec = copy.deepcopy(SHOTS)
    spec["scenes"][1]["visual"]["clip"] = True
    spec["scenes"][1]["visual"]["motion"] = "The lamp turns."
    episode_id = new_episode(sessions, spec)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")
    give_picture(sessions, stage.data_dir, episode_id, "a_s02_lamp")
    with sessions.begin() as session:
        queue.enqueue(
            session,
            job_type=CLIP_JOB,
            tag=JobTag.GPU,
            payload={"asset_id": "a_s02_lamp", "scene_id": "s02_lamp"},
            episode_id=episode_id,
        )

    # The job that was queued first runs first. Another clip still waits behind it.
    stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    assert stage.clips.released == 0


def test_the_card_is_given_back_when_no_other_clip_waits(
    stage: Stage, sessions: sessionmaker[Session]
) -> None:
    episode_id = new_episode(sessions, SHOTS)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")

    stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    assert stage.clips.released == 1


def test_comfyui_that_is_not_running_is_the_owners_to_start_and_stores_nothing(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    stage = Stage(
        sessions, tmp_path / "data", FakeClips(NeedsOwnerError("ComfyUI does not answer."))
    )
    episode_id = new_episode(sessions, SHOTS)
    give_picture(sessions, stage.data_dir, episode_id, "a_s01_hill")

    with pytest.raises(NeedsOwnerError, match="ComfyUI does not answer"):
        stage.run(episode_id, asset_id="a_s01_hill", scene_id="s01_hill")

    assert picture(sessions, episode_id, "a_s01_hill").clip is None
