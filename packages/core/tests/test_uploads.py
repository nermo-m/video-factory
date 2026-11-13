"""The owner's own pictures: what an upload must be and how file names are matched
(design doc section 10, FR-07)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from packages.core import uploads
from packages.core.uploads import Match, UploadError, Wanted, match_filenames, prepare_picture


def picture(
    size: tuple[int, int] = (900, 1600), kind: str = "PNG", mode: str = "RGB", **save: object
) -> bytes:
    stored = io.BytesIO()
    Image.new(mode, size, (40, 90, 160) if mode == "RGB" else (40, 90, 160, 128)).save(
        stored, format=kind, **save
    )
    return stored.getvalue()


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


@pytest.mark.parametrize("kind", ["PNG", "JPEG", "WEBP"])
def test_a_png_jpeg_or_webp_picture_is_stored_as_a_png_of_the_same_size(kind: str) -> None:
    prepared = prepare_picture(picture(kind=kind))

    stored = opened(prepared.data)
    assert stored.format == "PNG"
    assert stored.size == (prepared.width, prepared.height) == (900, 1600)
    assert stored.mode == "RGB"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a picture at all",
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        b"GIF89a" + b"\0" * 64,
    ],
)
def test_a_file_that_is_not_a_picture_is_refused(data: bytes) -> None:
    with pytest.raises(UploadError) as refused:
        prepare_picture(data)

    assert refused.value.code == "not_a_picture"


def test_a_gif_or_a_bitmap_is_refused_even_when_it_is_a_real_picture() -> None:
    for kind in ("GIF", "BMP"):
        with pytest.raises(UploadError) as refused:
            prepare_picture(picture(kind=kind))
        assert refused.value.code == "not_a_picture"


def test_a_cut_off_picture_is_refused() -> None:
    whole = picture(kind="JPEG")

    with pytest.raises(UploadError) as refused:
        prepare_picture(whole[: len(whole) // 3])

    assert refused.value.code == "not_a_picture"


def test_a_file_over_the_size_limit_is_refused_before_it_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(uploads, "MAX_BYTES", 1000)

    with pytest.raises(UploadError) as refused:
        prepare_picture(b"\0" * 1001)

    assert refused.value.code == "too_large"


def test_a_picture_with_too_many_pixels_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uploads, "MAX_PIXELS", 900 * 1600 - 1)

    with pytest.raises(UploadError) as refused:
        prepare_picture(picture())

    assert refused.value.code == "too_large"
    assert "900 by 1600" in str(refused.value)


def test_a_thumbnail_is_refused_and_told_how_small_it_is() -> None:
    with pytest.raises(UploadError) as refused:
        prepare_picture(picture(size=(200, 800)))

    assert refused.value.code == "too_small"
    assert "200 by 800" in str(refused.value)
    assert "256" in str(refused.value)


def test_a_very_large_picture_is_scaled_down_and_keeps_its_shape() -> None:
    prepared = prepare_picture(picture(size=(3000, 6000), kind="JPEG"))

    assert (prepared.width, prepared.height) == (2048, 4096)


def test_a_photo_taken_sideways_is_turned_upright_and_its_metadata_is_dropped() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: turn 90 degrees clockwise to see it upright.
    exif[0x010F] = "A camera maker"
    exif[0x8825] = {1: "N", 2: (52.0, 5.0, 0.0)}  # Where it was taken.
    sideways = picture(size=(1600, 900), kind="JPEG", exif=exif)
    assert opened(sideways).getexif()[0x0112] == 6

    prepared = prepare_picture(sideways)

    stored = opened(prepared.data)
    assert stored.size == (900, 1600), "upright"
    assert dict(stored.getexif()) == {}
    assert set(stored.info) <= {"dpi"}, "no text chunks, no profile, no metadata"
    assert b"A camera maker" not in prepared.data


def test_a_see_through_picture_is_stored_without_its_transparency() -> None:
    prepared = prepare_picture(picture(mode="RGBA"))

    assert opened(prepared.data).mode == "RGB"


# --- matching by file name (FR-07) ---------------------------------------------------------

WANTED = [
    Wanted("a_harbour"),
    Wanted("a_storm_sea"),
    Wanted("a_my_photo", filename="my photo of the keeper.jpg"),
]


def matched(*filenames: str) -> list[str | None]:
    return [match.asset_id for match in match_filenames(filenames, WANTED)]


def test_fr07_a_file_named_like_a_picture_is_matched_to_it() -> None:
    assert match_filenames(["a_harbour.png"], WANTED) == [Match("a_harbour.png", "a_harbour", None)]


def test_fr07_the_a_prefix_case_spaces_and_dashes_make_no_difference() -> None:
    assert matched("harbour.jpg", "A_Storm-Sea.WEBP", "Storm Sea.png") == [
        "a_harbour",
        "a_storm_sea",
        None,  # a_storm_sea is taken by the file before it
    ]


def test_fr07_the_file_name_the_plan_asks_for_matches_whatever_its_extension() -> None:
    assert matched("My Photo Of The Keeper.PNG") == ["a_my_photo"]
    assert matched("my_photo.png") == ["a_my_photo"]


def test_fr07_a_folder_in_front_of_the_name_is_ignored() -> None:
    assert matched(
        "pictures/episode 4/harbour.png", "C:\\Users\\me\\Pictures\\a_storm_sea.jpg"
    ) == [
        "a_harbour",
        "a_storm_sea",
    ]


def test_fr07_a_file_that_matches_nothing_says_why() -> None:
    nothing, wrong_kind, second = match_filenames(
        ["sunset.png", "a_harbour.gif", "a_harbour.png"], WANTED
    )[:3]
    again = match_filenames(["a_harbour.png", "harbour.jpg"], WANTED)[1]

    assert (nothing.asset_id, nothing.why) == (None, "No picture of this episode has this name.")
    assert (wrong_kind.asset_id, wrong_kind.why) == (None, "It is not a PNG, JPEG or WebP file.")
    assert second.asset_id == "a_harbour", "the file of the wrong kind did not take the picture"
    assert (again.asset_id, again.why) == (None, "Another file already matches a_harbour.")


def test_fr07_matching_keeps_the_order_and_the_names_it_was_given() -> None:
    names = ["z.png", "a_storm_sea.png", "harbour.webp"]

    assert [match.filename for match in match_filenames(names, WANTED)] == names


def test_fr07_a_name_is_never_used_as_a_path() -> None:
    assert matched("../../a_harbour.png", "..\\..\\etc\\passwd") == ["a_harbour", None]
