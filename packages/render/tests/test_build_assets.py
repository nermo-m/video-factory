"""The theme's artwork and sounds can be regenerated from code (rule 2: original assets).

The committed files must be exactly what build_assets.py draws. If someone edits an image
by hand, or changes the script without regenerating, this fails.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from packages.render.theme.night_scrolls import build_assets


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("assets")
    written = build_assets.build(folder)
    assert len(written) == len(build_assets.IMAGES) + len(build_assets.SOUNDS)
    return folder


@pytest.mark.parametrize("name", sorted(build_assets.IMAGES))
def test_rule2_committed_images_are_what_the_script_draws(name: str, rebuilt: Path) -> None:
    with Image.open(build_assets.ASSETS / name) as committed, Image.open(rebuilt / name) as fresh:
        assert committed.mode == fresh.mode
        assert committed.size == fresh.size
        difference = np.abs(
            np.asarray(committed, dtype=np.int16) - np.asarray(fresh, dtype=np.int16)
        )
    # Identical on the same platform. Across platforms the resampling filters may round
    # a pixel differently by one level, never more.
    assert int(difference.max()) <= 2, f"{name} was changed without the script"
    assert float(difference.mean()) < 0.05


@pytest.mark.parametrize("name", sorted(build_assets.SOUNDS))
def test_rule2_committed_sounds_are_what_the_script_synthesises(name: str, rebuilt: Path) -> None:
    def samples(path: Path) -> np.ndarray:
        with wave.open(str(path), "rb") as sound:
            assert sound.getframerate() == build_assets.SAMPLE_RATE
            return np.frombuffer(sound.readframes(sound.getnframes()), dtype="<i2").astype(np.int32)

    committed, fresh = samples(build_assets.ASSETS / name), samples(rebuilt / name)

    assert committed.shape == fresh.shape
    assert int(np.abs(committed - fresh).max()) <= 2, f"{name} was changed without the script"


def test_every_generated_asset_is_listed_once() -> None:
    generated = {*build_assets.IMAGES, *build_assets.SOUNDS}
    on_disk = {
        path.relative_to(build_assets.ASSETS).as_posix()
        for path in build_assets.ASSETS.rglob("*")
        if path.suffix in {".png", ".wav"}
    }

    assert generated == on_disk
