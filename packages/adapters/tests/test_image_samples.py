"""The picture interface and its demo twin (design doc section 3.3)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from packages.adapters.factory import Adapters
from packages.adapters.image import ImageRequest, SampleImages, png_size
from packages.adapters.image.samples import DEFAULT_SAMPLES_DIR
from packages.core.enums import Provider
from packages.core.queue import NeedsOwnerError
from packages.core.settings import Settings


def test_the_demo_adapter_returns_the_bundled_picture_with_that_id() -> None:
    result = SampleImages().create(ImageRequest(asset_id="a_hill_dawn", prompt="Anything."))

    assert result.data == (DEFAULT_SAMPLES_DIR / "a_hill_dawn.png").read_bytes()
    assert (result.width, result.height) == png_size(result.data)
    assert (result.provider, result.model, result.cost_usd) == (
        Provider.DEMO,
        "bundled samples",
        Decimal("0"),
    )
    assert result.licence == "MIT (bundled sample picture)"


def test_an_unknown_picture_gets_a_bundled_stand_in_and_always_the_same_one() -> None:
    adapter = SampleImages()

    first = adapter.create(ImageRequest(asset_id="a_harbour", prompt="A harbour."))
    again = adapter.create(ImageRequest(asset_id="a_harbour", prompt="Another prompt."))

    bundled = {path.read_bytes() for path in DEFAULT_SAMPLES_DIR.glob("*.png")}
    assert first.data in bundled
    assert again.data == first.data


def test_without_bundled_pictures_the_demo_adapter_says_what_is_missing(tmp_path: Path) -> None:
    with pytest.raises(NeedsOwnerError, match="bundled sample pictures are missing"):
        SampleImages(tmp_path).create(ImageRequest(asset_id="a_harbour", prompt="A harbour."))


@pytest.mark.parametrize(
    "data",
    [b"", b"not a picture", b"\x89PNG\r\n\x1a\n" + b"\x00" * 30, b"\x89PNG\r\n\x1a\n"],
)
def test_the_size_of_something_that_is_not_a_png_is_unknown(data: bytes) -> None:
    assert png_size(data) is None


def test_the_size_of_a_png_is_read_from_its_header() -> None:
    assert png_size((DEFAULT_SAMPLES_DIR / "a_hill_dawn.png").read_bytes()) is not None


def settings(mode: str) -> Settings:
    return Settings(database_url="postgresql://unused", provider_mode=mode)


def test_demo_mode_gets_the_bundled_pictures() -> None:
    assert isinstance(Adapters(settings("demo")).image(), SampleImages)


def test_api_mode_has_no_picture_adapter_yet_and_never_reaches_for_another_mode() -> None:
    with pytest.raises(NeedsOwnerError, match="API mode cannot make pictures yet"):
        Adapters(settings("api"), paid_apis_confirmed=True).image()
