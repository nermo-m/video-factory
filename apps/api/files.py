"""Stored files (design doc section 10): `GET /files/{path}`.

Serves what the worker stored below the data folder: videos, contact sheets, pictures and
narration. A video is served with range requests, so a player can seek.

Only media files are served, and only from below the data folder (NFR-01). Anything else
answers 404 without saying whether it exists: a path with `..` or `.` in it, an absolute
path, a backslash, a link that leads out of the folder, a folder, and every file that is
not one of the media types below.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from starlette.responses import FileResponse, MalformedRangeHeader, RangeNotSatisfiable

from apps.api.errors import ApiError, ErrorResponse

router = APIRouter(tags=["files"])

FILES_PREFIX = "/api/v1/files/"
MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".wav": "audio/wav",
}


def file_url(path: str | None) -> str | None:
    """The address of a stored file below this API, or None when there is no file."""
    return None if path is None else FILES_PREFIX + quote(path)


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "There is no such file.")


def stored_file(data_dir: str | Path, path: str) -> Path:
    """The media file a path names, or a 404."""
    asked = PurePosixPath(path)
    unsafe = (
        not path
        or "\\" in path
        or "\x00" in path
        or ":" in path
        or path.startswith("/")
        # PurePosixPath drops "." parts, so they are looked for in the text itself.
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or asked.suffix.lower() not in MEDIA_TYPES
    )
    if unsafe:
        raise _not_found()
    root = Path(data_dir).resolve()
    target = (root / asked).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise _not_found()
    return target


def _check_range(asked: str | None, size: int) -> None:
    """Refuse a range that cannot be served, in the common error shape.

    The file response would refuse the same ranges itself, but in plain text.
    """
    if asked is None:
        return
    try:
        # The response's own parser, so both always agree on what a good range is.
        FileResponse._parse_range_header(asked, size)
    except MalformedRangeHeader as error:
        raise ApiError(
            400,
            "bad_range",
            "The Range header could not be read. Ask for bytes, as in bytes=0-999.",
        ) from error
    except RangeNotSatisfiable as error:
        raise ApiError(
            416,
            "range_not_satisfiable",
            f"The file is {size} bytes long. The range that was asked for starts after its end.",
            headers={"Content-Range": f"bytes */{size}"},
        ) from error


_FILE: dict[str, Any] = {
    "description": "The file, or the part of it that was asked for.",
    "content": {media_type: {} for media_type in sorted(set(MEDIA_TYPES.values()))},
}


@router.get(
    "/files/{path:path}",
    summary="A stored video, picture or narration file",
    response_class=FileResponse,
    responses={
        200: _FILE,
        206: _FILE,
        400: {"model": ErrorResponse, "description": "The Range header could not be read."},
        404: {"model": ErrorResponse, "description": "There is no such media file."},
        416: {"model": ErrorResponse, "description": "The range starts after the end of the file."},
    },
)
def get_file(path: str, request: Request) -> FileResponse:
    target = stored_file(request.app.state.settings.data_dir, path)
    _check_range(request.headers.get("range"), target.stat().st_size)
    return FileResponse(target, media_type=MEDIA_TYPES[target.suffix.lower()])
