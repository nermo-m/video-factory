"""Fail when a repository asset has no row in ASSETS.md.

Design doc section 13, rule 2: everything in the repository is original or permissively
licensed, and every sample and media file is listed in ASSETS.md with its origin, licence
and source. This script is the automatic enforcement. It uses only the standard library
so it runs anywhere Python does.

A file needs a row when it is:

* any file under ``samples/`` (README.md files excepted), or
* a media file (image, font, audio, video) anywhere in the repository.

A row's path may be a glob: ``*`` and ``?`` stay inside one folder, ``**`` crosses folders.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REGISTRY_NAME = "ASSETS.md"
HEADER_CELLS = ("path", "origin", "licence", "source")

SAMPLES_PREFIX = "samples/"
MEDIA_SUFFIXES = frozenset(
    {
        # images
        ".avif", ".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp",
        # fonts
        ".otf", ".ttc", ".ttf", ".woff", ".woff2",
        # audio
        ".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav",
        # video
        ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm",
    }
)  # fmt: skip

ORIGINS = frozenset({"original", "generated", "third-party"})
PERMISSIVE_LICENCES = frozenset(
    {
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC-BY-4.0",
        "CC0-1.0",
        "ISC",
        "MIT",
        "OFL-1.1",
        "Unlicense",
        "Zlib",
    }
)

_SKIPPED_FOLDERS = frozenset({".git", ".venv", "node_modules"})
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")


@dataclass(frozen=True)
class Row:
    """One line of the ASSETS.md table."""

    line: int
    pattern: str
    origin: str
    licence: str
    source: str


def requires_row(path: str) -> bool:
    """Return True when the file at this repository-relative path must be registered."""
    pure = PurePosixPath(path)
    if path.startswith(SAMPLES_PREFIX):
        return pure.name != "README.md"
    return pure.suffix.lower() in MEDIA_SUFFIXES


def matches(pattern: str, path: str) -> bool:
    """Match a repository-relative path against a row pattern."""
    return _compile(pattern).fullmatch(path) is not None


def _compile(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts))


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_registry(text: str) -> tuple[list[Row], list[str]]:
    """Read the asset table. Returns the rows and any format problems."""
    rows: list[Row] = []
    problems: list[str] = []
    in_table = False
    found_header = False

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line.startswith("|"):
            in_table = False
            continue
        cells = _cells(line)
        if not in_table:
            if tuple(cell.lower() for cell in cells) == HEADER_CELLS:
                in_table = True
                found_header = True
            continue
        if all(_SEPARATOR_CELL.match(cell) for cell in cells):
            continue
        if len(cells) != len(HEADER_CELLS):
            problems.append(
                f"{REGISTRY_NAME} line {number}: expected {len(HEADER_CELLS)} cells "
                f"(path, origin, licence, source), found {len(cells)}"
            )
            continue
        pattern, origin, licence, source = cells
        rows.append(Row(number, pattern.strip("`"), origin, licence, source))

    if not found_header:
        problems.append(
            f"{REGISTRY_NAME}: no table with the header | Path | Origin | Licence | Source |"
        )
    return rows, problems


def _row_problems(row: Row, files: Sequence[str]) -> list[str]:
    where = f"{REGISTRY_NAME} line {row.line}"
    problems: list[str] = []
    if row.origin not in ORIGINS:
        allowed = ", ".join(sorted(ORIGINS))
        problems.append(f"{where}: origin '{row.origin}' is not one of {allowed}")
    if row.licence not in PERMISSIVE_LICENCES:
        problems.append(f"{where}: licence '{row.licence}' is not on the permissive list")
    if not row.source:
        problems.append(f"{where}: source is empty")
    if not any(matches(row.pattern, path) for path in files):
        problems.append(f"{where}: '{row.pattern}' matches no file")
    return problems


def check(files: Iterable[str], registry_text: str) -> list[str]:
    """Return every problem found. An empty list means the repository is clean."""
    all_files = sorted({path.replace("\\", "/") for path in files})
    rows, problems = parse_registry(registry_text)

    for row in rows:
        problems.extend(_row_problems(row, all_files))

    problems.extend(
        f"{path}: no row in {REGISTRY_NAME}"
        for path in all_files
        if requires_row(path) and not any(matches(row.pattern, path) for row in rows)
    )
    return problems


def list_repository_files(root: Path) -> list[str]:
    """List files that are tracked or about to be: git's view when available, else a walk."""
    git = shutil.which("git")
    if git is not None and (root / ".git").exists():
        # Fixed argument list, no shell, and the executable is resolved by shutil.which:
        # nothing here comes from untrusted input.
        result = subprocess.run(  # noqa: S603
            [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        listed = [name for name in result.stdout.decode("utf-8").split("\0") if name]
        return [name for name in listed if (root / name).is_file()]

    return [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and _SKIPPED_FOLDERS.isdisjoint(path.relative_to(root).parts)
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: the repository this script lives in)",
    )
    root: Path = parser.parse_args(argv).root

    registry_path = root / REGISTRY_NAME
    if not registry_path.is_file():
        sys.stderr.write(f"{REGISTRY_NAME} not found in {root}\n")
        return 1

    files = list_repository_files(root)
    problems = check(files, registry_path.read_text(encoding="utf-8"))
    if problems:
        sys.stderr.write("\n".join(problems) + "\n")
        sys.stderr.write(
            f"\n{len(problems)} problem(s). Every sample and media file needs a row in "
            f"{REGISTRY_NAME} with origin, licence and source.\n"
        )
        return 1

    registered = sum(1 for path in files if requires_row(path))
    sys.stdout.write(f"{REGISTRY_NAME} covers all {registered} asset file(s).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
