"""The voice and render steps with the real FFmpeg (design doc sections 4.1 and 7).

The same three steps the queue runs as `gen.voice`, `render.scene` and `render.join`, here
without a database: the sample episode is spoken from its bundled recordings, every scene
is encoded by itself, and the join makes a video that passes the format check of RN-01.
In preview size, so it takes seconds. Runs in the worker image: make render-test
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from apps.worker import demo_render
from apps.worker.handlers import produce
from apps.worker.main import build_handlers
from packages.adapters.storage import LocalStorage
from packages.adapters.tts.samples import SampleVoice
from packages.core.settings import Settings
from packages.core.stages import LAST_BUILT_STATE, STATES, index_of, plan_stage, stage_count
from packages.render.encode import for_preview, render_scene
from packages.render.theme import load_theme


def test_the_worker_has_a_handler_for_every_job_up_to_the_render_except_generation(
    tmp_path: Path,
) -> None:
    """The pipeline rests after the last built state, so every job before it must be one
    the worker can run. Generated pictures and clips are the known exception: they arrive
    in milestone M3, and until then a plan uses library pictures, which need no job."""
    sample = demo_render.load_sample()
    settings = Settings(database_url="postgresql://unused", data_dir=str(tmp_path))
    handlers = build_handlers(settings, sessionmaker[Session]())
    assert LAST_BUILT_STATE is not None

    needed = {
        request.job_type
        for state in STATES[: index_of(LAST_BUILT_STATE) + 1]
        for stage in range(stage_count(state))
        for request in plan_stage(state, stage, spec=sample)
    }

    assert needed <= set(handlers), "the sample episode needs no job without a handler"
    assert {"gen.voice", "render.scene", "render.join"} <= set(handlers)
    assert {"gen.image", "gen.clip"}.isdisjoint(handlers), "update this test in milestone M3"


@pytest.fixture(scope="module")
def chain(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Speak, encode scene by scene and join the sample episode, in preview size."""
    data_dir = tmp_path_factory.mktemp("data")
    storage = LocalStorage(data_dir)
    authored = demo_render.load_sample()
    tts = SampleVoice(demo_render.VOICE_DIR)

    voices = [
        produce.speak(tts, storage, authored, scene["id"], {}, PurePosixPath("jobs/voice/x"))
        for scene in authored["scenes"]
        if scene["narration"].strip()
    ]
    resolved = for_preview(
        produce.resolve_with(authored, voices, produce.stored_pictures(storage, authored), {})
    )
    scenes_folder = data_dir / "episodes" / "one" / "scenes"
    theme = load_theme(resolved["theme"])
    scenes = [
        render_scene(resolved, theme, scene["id"], storage_root=data_dir, folder=scenes_folder)
        for scene in resolved["scenes"]
    ]
    joined = produce.join_video(resolved, data_dir, scenes_folder, data_dir / "jobs" / "join" / "y")
    return {"data_dir": data_dir, "resolved": resolved, "scenes": scenes, "joined": joined}


@pytest.mark.render
def test_every_scene_job_makes_its_own_file(chain: dict[str, Any]) -> None:
    scenes = chain["scenes"]

    assert [scene.scene_id for scene in scenes] == [
        scene["id"] for scene in chain["resolved"]["scenes"]
    ]
    assert all(scene.path.is_file() and not scene.reused for scene in scenes)


@pytest.mark.render
def test_the_join_reuses_every_scene_file_and_passes_the_format_check(
    chain: dict[str, Any],
) -> None:
    joined: produce.Joined = chain["joined"]

    assert joined.problems == []
    assert all(scene.reused for scene in joined.scenes), "the join encodes nothing again"
    assert [scene.path for scene in joined.scenes] == [scene.path for scene in chain["scenes"]]
    assert joined.duration_s == pytest.approx(45.0, abs=2.0)
    assert joined.video.is_file()
    assert joined.contact_sheet.is_file()


@pytest.mark.render
def test_the_video_is_kept_apart_from_the_scene_files(chain: dict[str, Any]) -> None:
    joined: produce.Joined = chain["joined"]
    data_dir: Path = chain["data_dir"]

    assert joined.video.parent == data_dir / "jobs" / "join" / "y"
    assert not (joined.video.parent / "scenes").exists()
    assert all(
        scene.path.parent == data_dir / "episodes" / "one" / "scenes" for scene in joined.scenes
    )
