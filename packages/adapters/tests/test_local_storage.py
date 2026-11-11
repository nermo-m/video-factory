"""Local storage adapter (decision D9)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from packages.adapters.storage import LocalStorage
from packages.core.storage import StorageAdapter, StorageError


def test_d9_local_storage_satisfies_the_storage_interface(tmp_path: Path) -> None:
    storage: StorageAdapter = LocalStorage(tmp_path)

    storage.check()


def test_write_then_read_round_trips_and_creates_folders(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    path = PurePosixPath("jobs/noop/ab/abcdef/result.json")

    assert storage.exists(path) is False
    storage.write_bytes(path, b'{"ok": true}')

    assert storage.exists(path) is True
    assert storage.read_bytes("jobs/noop/ab/abcdef/result.json") == b'{"ok": true}'
    assert (tmp_path / "jobs" / "noop" / "ab" / "abcdef" / "result.json").is_file()


def test_write_replaces_the_file_and_leaves_no_temporary_files(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)

    storage.write_bytes("scene.mp4", b"first")
    storage.write_bytes("scene.mp4", b"second")

    assert storage.read_bytes("scene.mp4") == b"second"
    assert [item.name for item in tmp_path.iterdir()] == ["scene.mp4"]


@pytest.mark.parametrize(
    "path",
    ["../outside.txt", "a/../../outside.txt", "/etc/passwd", "C:/Windows/win.ini", "", "a\\..\\b"],
)
def test_paths_that_escape_the_root_are_refused(tmp_path: Path, path: str) -> None:
    storage = LocalStorage(tmp_path / "data")
    (tmp_path / "data").mkdir()

    with pytest.raises(StorageError, match="not a valid storage path"):
        storage.write_bytes(path, b"x")
    with pytest.raises(StorageError, match="not a valid storage path"):
        storage.read_bytes(path)
    assert not (tmp_path / "outside.txt").exists()


def test_reading_a_missing_file_says_so(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match=r"'missing.txt' does not exist"):
        LocalStorage(tmp_path).read_bytes("missing.txt")


def test_check_fails_when_the_folder_is_missing(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="The data folder does not exist"):
        LocalStorage(tmp_path / "nowhere").check()


def test_check_leaves_nothing_behind(tmp_path: Path) -> None:
    LocalStorage(tmp_path).check()

    assert list(tmp_path.iterdir()) == []
