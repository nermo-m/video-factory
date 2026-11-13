"""The owner's own pictures: checking an uploaded file and matching file names to the
pictures of a plan (design doc section 10 and FR-07, "Uploaded files are matched to assets
by filename").

An upload is untrusted input. It is opened with Pillow, which must recognise it as a PNG,
JPEG or WebP picture of a sensible size, and it is stored again as a plain PNG: turned the
way its camera meant it, without the camera's metadata (which can hold a location), and
never larger than a video frame needs.

This module is pure: bytes and names in, bytes and matches out.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 20 * 1024 * 1024
"""The largest file that is read at all."""
MAX_PIXELS = 50_000_000
"""The largest picture that is decoded (a 50 megapixel photo)."""
MIN_SIDE = 256
"""A picture smaller than this is a thumbnail, and would be a blur in a 1080 by 1920 video."""
MAX_SIDE = 4096
"""Larger pictures are scaled down: the video is 1080 by 1920, and a slow zoom needs less
than twice that."""
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
UPLOAD_LICENCE = "Uploaded by the owner"


class UploadError(ValueError):
    """An upload that is refused, with a code for the interface and words for the owner."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreparedPicture:
    """An upload as it is stored: a PNG without metadata."""

    data: bytes
    width: int
    height: int


def prepare_picture(data: bytes) -> PreparedPicture:
    """Check an uploaded file and return it as it is stored. Raises UploadError."""
    if len(data) > MAX_BYTES:
        raise UploadError("too_large", f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        with Image.open(io.BytesIO(data), formats=list(FORMATS)) as opened:
            width, height = opened.size
            if width * height > MAX_PIXELS:
                raise UploadError(
                    "too_large",
                    f"The picture is {width} by {height} pixels, which is more than "
                    f"{MAX_PIXELS // 1_000_000} megapixels. Make it smaller and upload it again.",
                )
            if min(width, height) < MIN_SIDE:
                raise UploadError(
                    "too_small",
                    f"The picture is {width} by {height} pixels. Its short side must be at "
                    f"least {MIN_SIDE} pixels, or it would be a blur in the video.",
                )
            # The first frame of an animated file, turned the way the camera meant it.
            opened.seek(0)
            picture = ImageOps.exif_transpose(opened.convert("RGB"))
    except UploadError:
        raise
    except Image.DecompressionBombError as error:
        raise UploadError("too_large", "The picture has too many pixels.") from error
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError) as error:
        raise UploadError(
            "not_a_picture", "This file is not a PNG, JPEG or WebP picture that can be read."
        ) from error

    if max(picture.size) > MAX_SIDE:
        picture.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    stored = io.BytesIO()
    # A new file: nothing of the original's metadata is written.
    picture.save(stored, format="PNG")
    return PreparedPicture(stored.getvalue(), picture.width, picture.height)


# --- matching by file name -----------------------------------------------------------------


@dataclass(frozen=True)
class Wanted:
    """A picture of the plan that a file can be matched to."""

    asset_id: str
    filename: str | None = None
    """The file name the plan asks for, when the picture is one the owner uploads."""


@dataclass(frozen=True)
class Match:
    filename: str
    asset_id: str | None
    why: str | None
    """Why the file matches nothing. None when it matched."""


def _name(filename: str) -> str:
    """The last part of a path, whichever way its slashes lean."""
    return PurePosixPath(PureWindowsPath(filename).as_posix()).name


def _stem(filename: str) -> str:
    """What a file name is compared by: its name without the extension, in lower case,
    with everything that is not a letter or a digit read as one underscore."""
    stem = PurePosixPath(_name(filename)).stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_")


def match_filenames(filenames: Sequence[str], wanted: Iterable[Wanted]) -> list[Match]:
    """Match file names to pictures (FR-07).

    A file belongs to a picture when its name, without the extension, is the picture's id
    (`a_harbour.png`), the id without its `a_` (`harbour.jpg`), or the file name the plan
    asks for. Upper and lower case, spaces and dashes make no difference. The first file
    that matches a picture gets it.
    """
    by_stem: dict[str, str] = {}
    for picture in wanted:
        names = [picture.asset_id, picture.asset_id.removeprefix("a_")]
        if picture.filename:
            names.append(picture.filename)
        for name in names:
            by_stem.setdefault(_stem(name), picture.asset_id)

    taken: set[str] = set()
    matches = []
    for filename in filenames:
        shown = _name(filename)
        if not shown.lower().endswith(EXTENSIONS):
            matches.append(Match(filename, None, "It is not a PNG, JPEG or WebP file."))
            continue
        asset_id = by_stem.get(_stem(filename))
        if asset_id is None:
            matches.append(Match(filename, None, "No picture of this episode has this name."))
        elif asset_id in taken:
            matches.append(Match(filename, None, f"Another file already matches {asset_id}."))
        else:
            taken.add(asset_id)
            matches.append(Match(filename, asset_id, None))
    return matches
