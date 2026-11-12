"""`make models`: download the voice model files and prove they are the expected ones."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from scripts.download_models import FILES, DownloadError, ModelFile, download, ensure

CONTENT = b"pretend model weights"
FILE = ModelFile(
    name="kokoro.onnx",
    url="https://example.invalid/kokoro.onnx",
    sha256=hashlib.sha256(CONTENT).hexdigest(),
    size=len(CONTENT),
)


class FakeFetch:
    def __init__(self, content: bytes = CONTENT) -> None:
        self.content = content
        self.urls: list[str] = []

    def __call__(self, url: str, target: Path) -> None:
        self.urls.append(url)
        target.write_bytes(self.content)


def test_a_missing_file_is_downloaded_under_its_final_name(tmp_path: Path) -> None:
    fetch = FakeFetch()

    result = ensure(FILE, tmp_path, fetch=fetch)

    assert result == "downloaded"
    assert fetch.urls == [FILE.url]
    assert (tmp_path / "kokoro.onnx").read_bytes() == CONTENT
    assert [path.name for path in tmp_path.iterdir()] == ["kokoro.onnx"]


def test_a_file_that_is_already_there_and_intact_is_not_downloaded_again(tmp_path: Path) -> None:
    (tmp_path / "kokoro.onnx").write_bytes(CONTENT)
    fetch = FakeFetch()

    assert ensure(FILE, tmp_path, fetch=fetch) == "present"
    assert fetch.urls == []


def test_a_damaged_file_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "kokoro.onnx").write_bytes(b"half a downl")

    assert ensure(FILE, tmp_path, fetch=FakeFetch()) == "downloaded"
    assert (tmp_path / "kokoro.onnx").read_bytes() == CONTENT


def test_a_download_with_the_wrong_checksum_is_thrown_away(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="checksum"):
        ensure(FILE, tmp_path, fetch=FakeFetch(b"something else"))

    # Neither the file nor a leftover partial download stays behind.
    assert list(tmp_path.iterdir()) == []


def test_the_folder_is_created_when_it_does_not_exist(tmp_path: Path) -> None:
    folder = tmp_path / "models" / "kokoro"

    ensure(FILE, folder, fetch=FakeFetch())

    assert (folder / "kokoro.onnx").is_file()


def test_only_https_addresses_are_downloaded(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="https"):
        download("http://example.invalid/kokoro.onnx", tmp_path / "x")
    with pytest.raises(DownloadError, match="https"):
        download("file:///etc/passwd", tmp_path / "x")


def test_the_pinned_files_are_the_two_the_voice_adapter_needs() -> None:
    assert [file.name for file in FILES] == ["kokoro.onnx", "voices.bin"]
    for file in FILES:
        assert file.url.startswith("https://github.com/")
        assert re.fullmatch(r"[0-9a-f]{64}", file.sha256)
        assert file.size > 1_000_000
