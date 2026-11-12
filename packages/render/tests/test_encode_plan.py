"""Which scenes need encoding (RN-04, RN-05, FR-12), tested without FFmpeg.

A scene file is named after a key: a hash of everything that can change the scene's
pixels. Rendering again encodes only the scenes whose key has changed. The encoder is
replaced by a stand-in here. The real one is tested in test_encode_ffmpeg.py.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from packages.render.compositor import scene_frame_counts
from packages.render.encode import for_preview, render_scenes, scene_keys
from packages.render.tests import support
from packages.render.theme import Theme, load_theme

PICTURE = "library/a_garden_dusk/v1.png"


@pytest.fixture(scope="module")
def theme() -> Theme:
    return load_theme("night_scrolls")


@pytest.fixture(scope="module")
def resolved() -> dict[str, Any]:
    return support.resolve_sample(support.sample_authored(), PICTURE)


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    folder = tmp_path / "storage"
    support.sample_picture(folder)
    return folder


class FakeEncoder:
    """Stands in for FFmpeg: writes a small file and remembers which scenes it was given."""

    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: list[int] = []
        self.fail_on = fail_on

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
        if index == self.fail_on:
            raise RuntimeError("the encoder stopped half way")


def changed_text(resolved: dict[str, Any], index: int) -> dict[str, Any]:
    """The same spec with one caption word of one scene rewritten."""
    edited = copy.deepcopy(resolved)
    edited["scenes"][index]["narration"]["words"][0]["text"] = "Changed"
    return edited


# --- keys ------------------------------------------------------------------------------


def test_every_scene_has_its_own_key_and_the_keys_are_stable(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    first = scene_keys(resolved, theme, storage)
    second = scene_keys(copy.deepcopy(resolved), theme, storage)

    assert first == second
    assert len(first) == len(resolved["scenes"])
    assert len(set(first)) == len(first)


def test_fr12_editing_one_scene_changes_only_that_scenes_key(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    before = scene_keys(resolved, theme, storage)
    after = scene_keys(changed_text(resolved, 0), theme, storage)

    changed = [
        index for index, (old, new) in enumerate(zip(before, after, strict=True)) if old != new
    ]
    assert changed == [0]


def test_rn03_a_transition_belongs_to_the_scene_it_leaves_and_the_scene_it_enters(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    before = scene_keys(resolved, theme, storage)
    edited = copy.deepcopy(resolved)
    assert edited["scenes"][1]["transition_out"] == "smoke"
    edited["scenes"][1]["transition_out"] = "cut"

    after = scene_keys(edited, theme, storage)

    changed = [
        index for index, (old, new) in enumerate(zip(before, after, strict=True)) if old != new
    ]
    assert changed == [1, 2]


@pytest.mark.parametrize("field", ["seed", "format"])
def test_the_seed_and_the_format_change_every_key(
    resolved: dict[str, Any], theme: Theme, storage: Path, field: str
) -> None:
    edited = copy.deepcopy(resolved)
    if field == "seed":
        edited["seed"] += 1
    else:
        edited["format"]["fps"] = 25

    before, after = scene_keys(resolved, theme, storage), scene_keys(edited, theme, storage)

    assert all(old != new for old, new in zip(before, after, strict=True))


def test_replacing_a_picture_changes_only_the_scenes_that_show_it(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    before = scene_keys(resolved, theme, storage)
    Image.new("RGB", (64, 64), (200, 30, 30)).save(storage / PICTURE)

    after = scene_keys(resolved, theme, storage)

    with_picture = [index for index, scene in enumerate(resolved["scenes"]) if "visual" in scene]
    changed = [
        index for index, (old, new) in enumerate(zip(before, after, strict=True)) if old != new
    ]
    assert changed == with_picture != []


def test_rn12_preview_is_540_by_960_at_15_fps_and_has_its_own_keys(
    resolved: dict[str, Any], theme: Theme, storage: Path
) -> None:
    preview = for_preview(resolved)

    assert preview["format"] == {**resolved["format"], "width": 540, "height": 960, "fps": 15}
    assert resolved["format"]["width"] == 1080
    assert set(scene_keys(preview, theme, storage)).isdisjoint(scene_keys(resolved, theme, storage))


# --- reuse -----------------------------------------------------------------------------


def test_rn02_the_first_render_encodes_every_scene_into_its_own_file(
    resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    encoder = FakeEncoder()

    scenes = render_scenes(
        resolved, theme, storage_root=storage, folder=tmp_path / "scenes", encode=encoder
    )

    assert encoder.calls == list(range(len(resolved["scenes"])))
    assert [scene.scene_id for scene in scenes] == [scene["id"] for scene in resolved["scenes"]]
    assert all(scene.path.is_file() and not scene.reused for scene in scenes)
    assert len({scene.path for scene in scenes}) == len(scenes)
    assert [scene.frames for scene in scenes] == scene_frame_counts(resolved)


def test_rn04_rendering_the_same_spec_again_encodes_nothing(
    resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "scenes"
    first = render_scenes(
        resolved, theme, storage_root=storage, folder=folder, encode=FakeEncoder()
    )
    encoder = FakeEncoder()

    again = render_scenes(resolved, theme, storage_root=storage, folder=folder, encode=encoder)

    assert encoder.calls == []
    assert all(scene.reused for scene in again)
    assert [scene.path for scene in again] == [scene.path for scene in first]


def test_fr12_changing_one_scene_re_encodes_only_that_scene(
    resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "scenes"
    first = render_scenes(
        resolved, theme, storage_root=storage, folder=folder, encode=FakeEncoder()
    )
    untouched = {scene.path: scene.path.stat().st_mtime_ns for scene in first}
    encoder = FakeEncoder()

    second = render_scenes(
        changed_text(resolved, 3), theme, storage_root=storage, folder=folder, encode=encoder
    )

    assert encoder.calls == [3]
    assert [scene.reused for scene in second] == [index != 3 for index in range(len(second))]
    assert second[3].path != first[3].path
    for index, scene in enumerate(second):
        if index != 3:
            assert scene.path.stat().st_mtime_ns == untouched[scene.path]


def test_rn05_a_failed_encode_leaves_no_file_that_looks_finished(
    resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "scenes"

    with pytest.raises(RuntimeError, match="half way"):
        render_scenes(
            resolved, theme, storage_root=storage, folder=folder, encode=FakeEncoder(fail_on=2)
        )

    # Scenes 0 and 1 finished and stay. Scene 2 left nothing behind, not even a partial file.
    left = sorted(path.name for path in folder.iterdir() if path.suffix == ".mp4")
    assert len(left) == 2
    assert all(name.startswith(("scene_00_", "scene_01_")) for name in left)
    assert not any("partial" in path.name for path in folder.iterdir())


def test_rn05_a_render_after_a_failure_picks_up_where_it_stopped(
    resolved: dict[str, Any], theme: Theme, storage: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "scenes"
    with pytest.raises(RuntimeError):
        render_scenes(
            resolved, theme, storage_root=storage, folder=folder, encode=FakeEncoder(fail_on=2)
        )
    encoder = FakeEncoder()

    scenes = render_scenes(resolved, theme, storage_root=storage, folder=folder, encode=encoder)

    assert encoder.calls == list(range(2, len(resolved["scenes"])))
    assert [scene.reused for scene in scenes[:2]] == [True, True]
