"""Job handlers that make the video (design doc sections 4.1 and 7).

* `gen.voice` speaks one scene's narration and keeps the audio file and its word timings.
* `render.scene` draws and encodes one scene into its own file.
* `render.join` mixes the sound, joins the scene files, draws the contact sheet, checks
  the finished file against RN-01 and stores it as a draft render with its resolved spec.

The two render jobs resolve the episode's current authored spec themselves, from the
voice that was spoken for the narration as it is now and from the stored pictures. The
resolver gives the same answer every time, so every scene job and the join agree.

Until the asset library of milestone M3 exists, the only pictures are the ones bundled
with the sample episode. They are copied into the storage the first time they are needed.

Paths: narration goes through the storage adapter, into the job's own folder. FFmpeg
writes below the same data folder: scene files into `episodes/<id>/scenes`, where the
next render finds the ones it can keep, and each joined video into the join job's own
folder, so an earlier video is never overwritten.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers.plan import current_spec
from apps.worker.runner import Handler, JobContext
from packages.adapters.tts import TTSAdapter, VoiceError
from packages.adapters.tts.samples import SampleVoice, sample_key
from packages.core.db.models import Channel, Episode, Job, Render, SpecVersion
from packages.core.enums import ErrorClass, JobStatus, RenderKind, SpecAuthor, SpecKind
from packages.core.queue import JobError, NeedsOwnerError
from packages.core.storage import StorageAdapter
from packages.render.encode import SceneEncoder, SceneFile, render_scene, render_video
from packages.render.probe import format_problems, probe_video
from packages.render.resolver import AssetFile, NarrationTiming, ResolveError, WordTiming, resolve
from packages.render.theme import load_theme

VOICE_JOB, SCENE_JOB, JOIN_JOB = "gen.voice", "render.scene", "render.join"
_SAMPLE_PICTURES = Path(__file__).resolve().parents[3] / "samples" / "lighthouse_keeper" / "assets"


@dataclass(frozen=True)
class Joined:
    """A finished video and what the format check found."""

    video: Path
    contact_sheet: Path
    duration_s: float
    scenes: list[SceneFile]
    problems: list[str]


# Joins a resolved spec into a video: (resolved, data folder, scenes folder, target folder).
Joiner = Callable[[Mapping[str, Any], Path, Path, Path], Joined]


# --- the steps, without the database -----------------------------------------------------


def narration_key(authored: Mapping[str, Any], text: str, pronunciation: Mapping[str, str]) -> str:
    """What a narration sounds like: its words, the voice, the speed and the pronunciation
    of its words. A voice file belongs to a scene only while this is unchanged."""
    voice = authored["voice"]
    return sample_key(
        text, voice_id=voice["voice_id"], speed=voice["speed"], pronunciation=pronunciation
    )


def speak(
    tts: TTSAdapter,
    storage: StorageAdapter,
    authored: Mapping[str, Any],
    scene_id: str,
    pronunciation: Mapping[str, str],
    folder: PurePosixPath,
) -> dict[str, Any]:
    """Speak one scene and store its audio. Returns the output of a `gen.voice` job."""
    scene = next((item for item in authored["scenes"] if item["id"] == scene_id), None)
    if scene is None or not scene["narration"].strip():
        raise JobError(
            f"The spec has no scene '{scene_id}' with narration to speak.",
            error_class=ErrorClass.BUG,
        )
    voice = authored["voice"]
    try:
        narration = tts.synthesise(
            scene["narration"],
            voice_id=voice["voice_id"],
            speed=voice["speed"],
            pronunciation=pronunciation or None,
        )
    except VoiceError as error:
        raise NeedsOwnerError(str(error)) from error
    stored = folder / f"{scene_id}.wav"
    storage.write_bytes(stored, narration.wav)
    return {
        "scene_id": scene_id,
        "audio_file": stored.as_posix(),
        "duration_s": narration.duration_s,
        "words": [asdict(word) for word in narration.words],
        "engine": narration.engine,
        "narration_key": narration_key(authored, scene["narration"], pronunciation),
    }


def stored_pictures(storage: StorageAdapter, authored: Mapping[str, Any]) -> dict[str, AssetFile]:
    """Where each picture of the spec is stored, copying the bundled ones in when needed."""
    files: dict[str, AssetFile] = {}
    missing: list[str] = []
    for asset in authored["assets"]:
        bundled = _SAMPLE_PICTURES / f"{asset['id']}.png"
        if not bundled.is_file():
            missing.append(asset["id"])
            continue
        stored = f"library/{asset['id']}/v1.png"
        if not storage.exists(stored):
            storage.write_bytes(stored, bundled.read_bytes())
        files[asset["id"]] = AssetFile(file=stored, licence=asset.get("licence"))
    if missing:
        known = ", ".join(sorted(path.stem for path in _SAMPLE_PICTURES.glob("*.png")))
        raise NeedsOwnerError(
            f"These pictures do not exist yet: {', '.join(missing)}. Making and uploading "
            "pictures arrives with the asset library. Until then a plan can use the "
            f"pictures of the sample episode: {known}."
        )
    return files


def resolve_with(
    authored: Mapping[str, Any],
    voices: Sequence[Mapping[str, Any]],
    files: Mapping[str, AssetFile],
    pronunciation: Mapping[str, str],
) -> dict[str, Any]:
    """Resolve the spec with the voice that was spoken for its narration as it is now.

    `voices` are the outputs of the episode's `gen.voice` jobs, newest first.
    """
    wanted = {
        scene["id"]: narration_key(authored, scene["narration"], pronunciation)
        for scene in authored["scenes"]
        if scene["narration"].strip()
    }
    spoken: dict[str, NarrationTiming] = {}
    for voice in voices:
        scene_id = voice.get("scene_id")
        if (
            isinstance(scene_id, str)
            and scene_id not in spoken
            and wanted.get(scene_id) == voice.get("narration_key")
        ):
            spoken[scene_id] = NarrationTiming(
                audio_file=voice["audio_file"],
                duration_s=voice["duration_s"],
                words=[WordTiming(**word) for word in voice["words"]],
            )
    silent = [scene_id for scene_id in wanted if scene_id not in spoken]
    if silent:
        raise NeedsOwnerError(
            f"These scenes have no voice for their narration as it is now: {', '.join(silent)}. "
            "Run the voice step again, then the render."
        )
    try:
        return resolve(authored, spoken, files)
    except ResolveError as error:
        raise NeedsOwnerError(str(error)) from error


def join_video(
    resolved: Mapping[str, Any], data_dir: Path, scenes_folder: Path, folder: Path
) -> Joined:
    """Mix, join, draw the contact sheet and check the finished file (RN-01)."""
    rendered = render_video(
        resolved,
        load_theme(resolved["theme"]),
        storage_root=data_dir,
        folder=folder,
        scenes_folder=scenes_folder,
    )
    problems = format_problems(probe_video(rendered.video), resolved["format"], rendered.duration_s)
    return Joined(
        video=rendered.video,
        contact_sheet=rendered.contact_sheet,
        duration_s=rendered.duration_s,
        scenes=rendered.scenes,
        problems=problems,
    )


def cached_voice(make: Callable[[], TTSAdapter]) -> Callable[[], TTSAdapter]:
    """The worker's voice. The real voice loads a large model, so it is made once and
    kept. While only bundled recordings are there, the model files are looked for again
    on every call, so `make models` takes effect without a restart."""
    lock = threading.Lock()
    kept: list[TTSAdapter] = []

    def voice() -> TTSAdapter:
        with lock:
            if kept:
                return kept[0]
            made = make()
            if not isinstance(made, SampleVoice):
                kept.append(made)
            return made

    return voice


# --- the handlers ------------------------------------------------------------------------


def _scene_id(context: JobContext) -> str:
    scene_id = context.job.input.get("scene_id")
    if not isinstance(scene_id, str) or not scene_id:
        raise JobError(f"A '{context.job.type}' job needs a scene_id.", error_class=ErrorClass.BUG)
    return scene_id


def _episode(session: Session, episode_id: uuid.UUID | None) -> tuple[Episode, Channel]:
    episode = session.get(Episode, episode_id) if episode_id is not None else None
    if episode is None:
        raise JobError("A voice or render job needs an episode.", error_class=ErrorClass.BUG)
    channel = session.get(Channel, episode.channel_id)
    assert channel is not None  # noqa: S101 - the foreign key guarantees it
    return episode, channel


def _voices(session: Session, episode_id: uuid.UUID) -> list[dict[str, Any]]:
    """The outputs of the episode's finished voice jobs, newest first."""
    outputs = session.scalars(
        select(Job.output)
        .where(
            Job.episode_id == episode_id,
            Job.type == VOICE_JOB,
            Job.status == JobStatus.SUCCEEDED,
        )
        .order_by(Job.finished_at.desc(), Job.created_at.desc())
    ).all()
    return [output for output in outputs if isinstance(output, dict)]


def scenes_path(episode_id: uuid.UUID) -> PurePosixPath:
    """Where an episode's scene files live, relative to the data folder."""
    return PurePosixPath("episodes") / str(episode_id) / "scenes"


def _relative(path: Path, data_dir: Path) -> str:
    return path.resolve().relative_to(data_dir.resolve()).as_posix()


def _store_render(
    session: Session,
    episode_id: uuid.UUID,
    resolved: Mapping[str, Any],
    joined: Joined,
    data_dir: Path,
) -> Render:
    """Store the video as a draft render. A retry of the same job finds what it stored."""
    episode = session.get(Episode, episode_id, with_for_update=True)
    assert episode is not None  # noqa: S101 - the job belongs to it
    video = _relative(joined.video, data_dir)
    existing = session.scalar(
        select(Render).where(Render.episode_id == episode_id, Render.file_path == video)
    )
    if existing is not None:
        return existing

    body = dict(resolved)
    spec = session.scalar(
        select(SpecVersion)
        .where(SpecVersion.episode_id == episode_id, SpecVersion.kind == SpecKind.RESOLVED)
        .order_by(SpecVersion.version.desc())
        .limit(1)
    )
    if spec is None or spec.body != body or spec.parent_id != episode.current_spec_id:
        newest = session.scalar(
            select(func.max(SpecVersion.version)).where(SpecVersion.episode_id == episode_id)
        )
        spec = SpecVersion(
            episode_id=episode_id,
            version=(newest or 0) + 1,
            kind=SpecKind.RESOLVED,
            body=body,
            # Whoever wrote the plan, the app worked out the times.
            author=SpecAuthor.MODEL,
            parent_id=episode.current_spec_id,
        )
        session.add(spec)
        session.flush()

    render = Render(
        episode_id=episode_id,
        resolved_spec_id=spec.id,
        kind=RenderKind.DRAFT,
        file_path=video,
        scene_files=[
            {
                "scene_id": scene.scene_id,
                "file": _relative(scene.path, data_dir),
                "key": scene.key,
                "frames": scene.frames,
            }
            for scene in joined.scenes
        ],
        contact_sheet_path=_relative(joined.contact_sheet, data_dir),
        duration_s=joined.duration_s,
    )
    session.add(render)
    session.flush()
    return render


def produce_handlers(
    sessions: sessionmaker[Session],
    *,
    storage: StorageAdapter,
    data_dir: Path,
    tts: Callable[[], TTSAdapter],
    encode: SceneEncoder | None = None,
    joiner: Joiner = join_video,
) -> dict[str, Handler]:
    """The handlers, for a worker that has a database, a data folder and a voice.

    `data_dir` is the folder the storage adapter writes to: FFmpeg reads and writes there
    directly. `encode` and `joiner` are replaced in tests that run without FFmpeg.
    """
    # The voice model is not made to run twice at the same moment in one process.
    one_voice = threading.Lock()

    def resolved_now(session: Session, episode_id: uuid.UUID | None) -> dict[str, Any]:
        episode, channel = _episode(session, episode_id)
        authored = current_spec(session, episode)
        return resolve_with(
            authored,
            _voices(session, episode.id),
            stored_pictures(storage, authored),
            dict(channel.pronunciation or {}),
        )

    def voice(context: JobContext) -> Mapping[str, Any]:
        scene_id = _scene_id(context)
        with sessions() as session:
            episode, channel = _episode(session, context.job.episode_id)
            authored = current_spec(session, episode)
            pronunciation = dict(channel.pronunciation or {})
        with one_voice:
            return speak(tts(), storage, authored, scene_id, pronunciation, context.output_path)

    def scene(context: JobContext) -> Mapping[str, Any]:
        scene_id = _scene_id(context)
        episode_id = context.job.episode_id
        with sessions() as session:
            resolved = resolved_now(session, episode_id)
        assert episode_id is not None  # noqa: S101 - resolved_now refused a job without one
        made = render_scene(
            resolved,
            load_theme(resolved["theme"]),
            scene_id,
            storage_root=data_dir,
            folder=data_dir / scenes_path(episode_id),
            encode=encode,
        )
        return {
            "scene_id": made.scene_id,
            "file": _relative(made.path, data_dir),
            "key": made.key,
            "frames": made.frames,
            "reused": made.reused,
        }

    def join(context: JobContext) -> Mapping[str, Any]:
        episode_id = context.job.episode_id
        with sessions() as session:
            resolved = resolved_now(session, episode_id)
        assert episode_id is not None  # noqa: S101 - resolved_now refused a job without one
        joined = joiner(
            resolved, data_dir, data_dir / scenes_path(episode_id), data_dir / context.output_path
        )
        if joined.problems:
            raise JobError(
                "The rendered video is not in the required format: " + " ".join(joined.problems),
                error_class=ErrorClass.BUG,
            )
        with sessions.begin() as session:
            render = _store_render(session, episode_id, resolved, joined, data_dir)
            return {
                "render_id": str(render.id),
                "video": render.file_path,
                "contact_sheet": render.contact_sheet_path,
                "duration_s": render.duration_s,
                "encoded": [item.scene_id for item in joined.scenes if not item.reused],
            }

    return {VOICE_JOB: voice, SCENE_JOB: scene, JOIN_JOB: join}
