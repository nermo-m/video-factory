"""The voice and render jobs on a real Postgres (design doc sections 4.1, 4.3 and 7).

`gen.voice` speaks with the bundled recordings here, as demo mode does without the voice
model. FFmpeg is not on the test machine, so the scene encoder and the join are replaced by
stand-ins. The real ones run in the worker image, in test_produce_render.py.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker import demo_render
from apps.worker.handlers import produce
from apps.worker.runner import JobContext
from packages.adapters.storage import LocalStorage
from packages.adapters.tts.samples import SampleVoice
from packages.core import queue, schemas
from packages.core.db import models
from packages.core.enums import ErrorClass, JobStatus, JobTag, RenderKind, SpecAuthor, SpecKind
from packages.core.queue import JobError
from packages.core.specs import store_spec
from packages.render.compositor import scene_frame_counts
from packages.render.encode import SceneFile
from packages.render.theme import Theme

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture(scope="module")
def sample() -> dict[str, Any]:
    return demo_render.load_sample()


@pytest.fixture
def episode_id(sessions: sessionmaker[Session], sample: dict[str, Any]) -> uuid.UUID:
    """An episode whose current spec is the sample episode, as the direction job leaves it."""
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="night_scrolls")
        session.add(channel)
        session.flush()
        episode = models.Episode(channel_id=channel.id, idea="A keeper who climbs a hill.")
        session.add(episode)
        session.flush()
        store_spec(session, episode.id, sample, author=SpecAuthor.MODEL)
        return episode.id


class FakeEncoder:
    """Stands in for FFmpeg: writes a small file and remembers which scenes it was given."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(
        self,
        resolved: Mapping[str, Any],
        theme: Theme,
        index: int,
        path: Path,
        storage_root: Path | None,
    ) -> None:
        self.calls.append(index)
        path.write_bytes(f"scene {index}".encode())


class FakeJoiner:
    """Stands in for the join: writes the two files and reports no format problems."""

    def __init__(self, problems: list[str] | None = None) -> None:
        self.problems = problems or []
        self.resolved: list[Mapping[str, Any]] = []

    def __call__(
        self, resolved: Mapping[str, Any], data_dir: Path, scenes_folder: Path, folder: Path
    ) -> produce.Joined:
        self.resolved.append(resolved)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "video.mp4").write_bytes(b"video")
        (folder / "video_contact_sheet.jpg").write_bytes(b"sheet")
        counts = scene_frame_counts(resolved)
        scenes = [
            SceneFile(
                index,
                scene["id"],
                f"key{index}",
                scenes_folder / f"scene_{index:02d}.mp4",
                counts[index],
                reused=True,
            )
            for index, scene in enumerate(resolved["scenes"])
        ]
        return produce.Joined(
            video=folder / "video.mp4",
            contact_sheet=folder / "video_contact_sheet.jpg",
            duration_s=44.2,
            scenes=scenes,
            problems=list(self.problems),
        )


class Stage:
    """A worker's handlers over one data folder, with a way to run one job as it would."""

    def __init__(self, sessions: sessionmaker[Session], data_dir: Path) -> None:
        self.sessions = sessions
        self.data_dir = data_dir
        self.encoder = FakeEncoder()
        self.joiner = FakeJoiner()
        self.handlers = produce.produce_handlers(
            sessions,
            storage=LocalStorage(data_dir),
            data_dir=data_dir,
            tts=lambda: SampleVoice(demo_render.VOICE_DIR),
            encode=self.encoder,
            joiner=self.joiner,
        )

    def run(self, job_type: str, episode_id: uuid.UUID, **payload: Any) -> dict[str, Any]:
        with self.sessions.begin() as session:
            queue.enqueue(
                session, job_type=job_type, tag=JobTag.CPU, payload=payload, episode_id=episode_id
            )
        with self.sessions.begin() as session:
            claim = queue.claim_next(session, JobTag.CPU)
        assert claim is not None
        context = JobContext(claim, queue.job_output_path(claim.type, claim.input_hash))
        try:
            output = dict(self.handlers[job_type](context) or {})
        except JobError as error:
            with self.sessions.begin() as session:
                queue.fail(session, claim, error.error_class, str(error))
            raise
        with self.sessions.begin() as session:
            queue.complete(session, claim, output)
        return output

    def speak_all(self, episode_id: uuid.UUID, spec: dict[str, Any]) -> None:
        for scene in spec["scenes"]:
            if scene["narration"].strip():
                self.run("gen.voice", episode_id, scene_id=scene["id"])


@pytest.fixture
def stage(sessions: sessionmaker[Session], tmp_path: Path) -> Stage:
    return Stage(sessions, tmp_path / "data")


def edit_spec(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, sample: dict[str, Any], **changes: Any
) -> dict[str, Any]:
    """Store a changed copy of the sample as the episode's current spec."""
    edited = copy.deepcopy(sample)
    for scene in edited["scenes"]:
        if scene["id"] in changes:
            scene.update(changes[scene["id"]])
    if "format" in changes:
        edited["format"].update(changes["format"])
    if "assets" in changes:
        edited["assets"] = changes["assets"]
    with sessions.begin() as session:
        store_spec(session, episode_id, edited, author=SpecAuthor.OWNER)
    return edited


# --- gen.voice ---------------------------------------------------------------------------


def test_fr10_a_scene_is_spoken_and_its_file_and_word_timings_are_kept(
    stage: Stage, episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    output = stage.run("gen.voice", episode_id, scene_id="s01_hook")

    narration = sample["scenes"][0]["narration"]
    assert output["scene_id"] == "s01_hook"
    assert output["engine"] == "sample"
    assert output["duration_s"] > 1
    assert [word["text"] for word in output["words"]] == narration.split()
    assert all(word["end_s"] >= word["start_s"] for word in output["words"])
    stored = stage.data_dir / output["audio_file"]
    assert stored.read_bytes()[:4] == b"RIFF"
    assert output["audio_file"].startswith("jobs/gen.voice/"), "a retry writes the same file"


def test_a_narration_the_bundled_voice_does_not_know_is_an_owner_task(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    edit_spec(sessions, episode_id, sample, s01_hook={"narration": "Words nobody has recorded."})

    with pytest.raises(JobError) as refused:
        stage.run("gen.voice", episode_id, scene_id="s01_hook")

    assert refused.value.error_class is ErrorClass.NEEDS_OWNER
    assert "make models" in str(refused.value)


def test_a_voice_job_for_a_scene_that_is_not_in_the_spec_is_a_bug(
    stage: Stage, episode_id: uuid.UUID
) -> None:
    with pytest.raises(JobError) as refused:
        stage.run("gen.voice", episode_id, scene_id="s99_missing")

    assert refused.value.error_class is ErrorClass.BUG
    assert "s99_missing" in str(refused.value)


# --- render.scene ------------------------------------------------------------------------


def test_fr12_a_scene_job_encodes_its_scene_only_and_stores_the_bundled_pictures(
    stage: Stage, episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    stage.speak_all(episode_id, sample)

    output = stage.run("render.scene", episode_id, scene_id="s02_climb")

    assert stage.encoder.calls == [1]
    assert output["scene_id"] == "s02_climb"
    assert output["reused"] is False
    assert output["file"].startswith(f"episodes/{episode_id}/scenes/scene_01_s02_climb_")
    assert (stage.data_dir / output["file"]).is_file()
    for asset in sample["assets"]:
        assert (stage.data_dir / "library" / asset["id"] / "v1.png").is_file()


def test_rn04_a_scene_job_that_runs_again_encodes_nothing(
    stage: Stage, episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    stage.speak_all(episode_id, sample)
    first = stage.run("render.scene", episode_id, scene_id="s02_climb")

    again = stage.run("render.scene", episode_id, scene_id="s02_climb", run=2)

    assert again["file"] == first["file"]
    assert again["reused"] is True
    assert stage.encoder.calls == [1]


def test_a_scene_cannot_be_drawn_before_every_narration_is_spoken(
    stage: Stage, episode_id: uuid.UUID
) -> None:
    stage.run("gen.voice", episode_id, scene_id="s01_hook")

    with pytest.raises(JobError) as refused:
        stage.run("render.scene", episode_id, scene_id="s01_hook")

    assert refused.value.error_class is ErrorClass.NEEDS_OWNER
    assert "s02_climb" in str(refused.value)
    assert "s01_hook" not in str(refused.value)
    assert stage.encoder.calls == []


def test_a_voice_that_was_spoken_for_other_words_is_not_used(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    stage.speak_all(episode_id, sample)
    edit_spec(sessions, episode_id, sample, s01_hook={"narration": "Words nobody has recorded."})

    with pytest.raises(JobError) as refused:
        stage.run("render.scene", episode_id, scene_id="s02_climb")

    assert refused.value.error_class is ErrorClass.NEEDS_OWNER
    assert "s01_hook" in str(refused.value)
    assert "voice" in str(refused.value)


def test_a_picture_that_was_never_made_is_an_owner_task_that_names_it(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    assets = copy.deepcopy(sample["assets"])
    assets.append(
        {
            "id": "a_new_harbour",
            "kind": "image",
            "origin": "generated",
            "prompt": "A small harbour at first light, flat shapes.",
            "contains_third_party_ip": False,
            "rights_status": "cleared",
        }
    )
    stage.speak_all(episode_id, sample)
    edited = edit_spec(sessions, episode_id, sample, assets=assets)
    assert schemas.validate("episode_spec", edited) == []

    with pytest.raises(JobError) as refused:
        stage.run("render.scene", episode_id, scene_id="s02_climb")

    assert refused.value.error_class is ErrorClass.NEEDS_OWNER
    assert "a_new_harbour" in str(refused.value)


def test_a_plan_that_does_not_fit_its_length_says_which_scenes_to_shorten(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    stage.speak_all(episode_id, sample)
    edit_spec(sessions, episode_id, sample, format={"target_duration_s": 30})

    with pytest.raises(JobError) as refused:
        stage.run("render.scene", episode_id, scene_id="s02_climb")

    assert refused.value.error_class is ErrorClass.NEEDS_OWNER
    assert "Shorten these scenes" in str(refused.value)


# --- render.join -------------------------------------------------------------------------


def test_the_join_stores_the_video_as_a_draft_render_with_its_resolved_spec(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    stage.speak_all(episode_id, sample)

    output = stage.run("render.join", episode_id)

    with sessions() as session:
        render = session.scalars(select(models.Render)).one()
        resolved = session.get(models.SpecVersion, render.resolved_spec_id)
        episode = session.get(models.Episode, episode_id)
        assert resolved is not None
        assert episode is not None
        current = session.get(models.SpecVersion, episode.current_spec_id)
        assert current is not None
    assert output["render_id"] == str(render.id)
    assert render.kind is RenderKind.DRAFT
    assert render.file_path == output["video"]
    assert render.file_path is not None
    assert render.file_path.startswith("jobs/render.join/")
    assert render.file_path.endswith("/video.mp4")
    assert (stage.data_dir / render.file_path).read_bytes() == b"video"
    assert render.contact_sheet_path == output["contact_sheet"]
    assert render.duration_s == pytest.approx(44.2)
    assert [scene["scene_id"] for scene in render.scene_files] == [
        scene["id"] for scene in sample["scenes"]
    ]
    assert all(
        scene["file"].startswith(f"episodes/{episode_id}/scenes/") for scene in render.scene_files
    )
    assert resolved.kind is SpecKind.RESOLVED
    assert resolved.body == stage.joiner.resolved[0]
    assert resolved.parent_id == current.id
    assert schemas.validate("resolved_spec", resolved.body) == []
    assert current.kind is SpecKind.AUTHORED, "the episode still points at its authored spec"


def test_a_join_that_is_run_again_for_the_same_job_stores_one_render(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    stage.speak_all(episode_id, sample)
    with sessions.begin() as session:
        queue.enqueue(session, job_type="render.join", tag=JobTag.CPU, episode_id=episode_id)
    with sessions.begin() as session:
        claim = queue.claim_next(session, JobTag.CPU)
    assert claim is not None
    context = JobContext(claim, queue.job_output_path(claim.type, claim.input_hash))

    first = stage.handlers["render.join"](context)
    again = stage.handlers["render.join"](context)

    with sessions() as session:
        renders = session.scalars(select(models.Render)).all()
        resolved = session.scalars(
            select(models.SpecVersion).where(models.SpecVersion.kind == SpecKind.RESOLVED)
        ).all()
    assert first == again
    assert len(renders) == 1
    assert len(resolved) == 1


def test_a_video_in_the_wrong_format_fails_the_job_and_stores_no_render(
    sessions: sessionmaker[Session], tmp_path: Path, episode_id: uuid.UUID, sample: dict[str, Any]
) -> None:
    stage = Stage(sessions, tmp_path / "data")
    stage.joiner.problems = ["The frame rate is 25.00, not 30."]
    stage.handlers = produce.produce_handlers(
        sessions,
        storage=LocalStorage(stage.data_dir),
        data_dir=stage.data_dir,
        tts=lambda: SampleVoice(demo_render.VOICE_DIR),
        encode=stage.encoder,
        joiner=stage.joiner,
    )
    stage.speak_all(episode_id, sample)

    with pytest.raises(JobError) as refused:
        stage.run("render.join", episode_id)

    assert refused.value.error_class is ErrorClass.BUG
    assert "The frame rate is 25.00, not 30." in str(refused.value)
    with sessions() as session:
        assert session.scalars(select(models.Render)).all() == []
        failed = session.scalars(select(models.Job).where(models.Job.type == "render.join")).one()
    assert failed.status is JobStatus.FAILED


# --- the voice of the worker -------------------------------------------------------------


def test_the_real_voice_is_made_once_and_bundled_recordings_are_looked_for_again() -> None:
    made: list[object] = []

    class Real:
        pass

    def make() -> Any:
        made.append(Real() if len(made) >= 2 else SampleVoice(demo_render.VOICE_DIR))
        return made[-1]

    voice = produce.cached_voice(make)

    first, second, third, fourth = voice(), voice(), voice(), voice()

    assert isinstance(first, SampleVoice)
    assert isinstance(second, SampleVoice)
    assert third is fourth, "once the model files are there, the loaded voice is kept"
    assert len(made) == 3
