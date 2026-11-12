"""Download the Kokoro voice model files (`make models`).

The files are too large for the repository (about 340 MB together) and are never
committed. Each one is checked against a pinned SHA-256 checksum, so a damaged download or
a changed file upstream is refused. A file that is already present and intact is kept.

Source: the model files published with the kokoro-onnx project (MIT). The model itself is
Kokoro-82M v1.0 by hexgrad (Apache-2.0). This script uses only the standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
DEFAULT_FOLDER = Path("models") / "kokoro"
TIMEOUT_S = 60
_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ModelFile:
    name: str  # the name it is stored under, as in KOKORO_MODEL_PATH and KOKORO_VOICES_PATH
    url: str
    sha256: str
    size: int


FILES = (
    ModelFile(
        name="kokoro.onnx",
        url=f"{RELEASE}/kokoro-v1.0.onnx",
        sha256="7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
        size=325_532_387,
    ),
    ModelFile(
        name="voices.bin",
        url=f"{RELEASE}/voices-v1.0.bin",
        sha256="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
        size=28_214_398,
    ),
)


class DownloadError(Exception):
    """A model file could not be downloaded or is not the expected file."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    """Fetch one file over HTTPS into `target`."""
    if not url.startswith("https://"):
        raise DownloadError(f"Only https addresses are downloaded, not {url}")
    try:
        # The scheme is checked above, so this cannot open a file or a plain-http address.
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response, target.open("wb") as file:  # noqa: S310
            shutil.copyfileobj(response, file, _CHUNK)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DownloadError(f"Could not download {url}: {error}") from error


def ensure(file: ModelFile, folder: Path, *, fetch: Callable[[str, Path], None] = download) -> str:
    """Make sure one model file is in the folder. Returns "present" or "downloaded"."""
    target = folder / file.name
    if target.is_file() and sha256_of(target) == file.sha256:
        return "present"
    folder.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        fetch(file.url, partial)
        actual = sha256_of(partial)
        if actual != file.sha256:
            raise DownloadError(
                f"{file.name} has the wrong checksum: expected {file.sha256}, got {actual}. "
                "The download was thrown away. Try again, and if it happens twice the file "
                "has changed at its source."
            )
        # Renamed only when complete and correct, so a half download never looks finished.
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return "downloaded"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the Kokoro voice model files.")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    arguments = parser.parse_args(argv)

    for file in FILES:
        sys.stdout.write(f"{file.name} ({file.size / 1_000_000:.0f} MB) ... ")
        sys.stdout.flush()
        try:
            result = ensure(file, arguments.folder)
        except DownloadError as error:
            sys.stdout.write("failed\n")
            sys.stderr.write(f"{error}\n")
            return 1
        sys.stdout.write("already there\n" if result == "present" else "downloaded\n")
    sys.stdout.write(f"The voice model is ready in {arguments.folder.as_posix()}/\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
