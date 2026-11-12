"""`GET /files/{path}`: stored media, with range requests for video (design doc section 10).

Only media files below the data folder are served. Every way out of that folder, and
every other kind of file, answers 404 in the common error shape (NFR-01).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.episodes import MemoryEpisodeService
from apps.api.errors import ApiError
from apps.api.files import file_url, stored_file
from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import API_PREFIX, create_app
from apps.api.providers import MemoryProviderService
from apps.api.settings import MemorySettingStore
from packages.core.settings import Settings

VIDEO = "jobs/render.join/ab/abcdef/video.mp4"
CONTENT = bytes(range(256)) * 4  # 1024 bytes, each position recognisable


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    (folder / "jobs" / "render.join" / "ab" / "abcdef").mkdir(parents=True)
    (folder / VIDEO).write_bytes(CONTENT)
    (folder / "jobs" / "render.join" / "ab" / "abcdef" / "video_contact_sheet.jpg").write_bytes(
        b"jpeg"
    )
    (folder / "library" / "a_hill_dawn").mkdir(parents=True)
    (folder / "library" / "a_hill_dawn" / "v1.png").write_bytes(b"png")
    (folder / "jobs" / "gen.voice").mkdir()
    (folder / "jobs" / "gen.voice" / "s01_hook.wav").write_bytes(b"RIFF")
    (folder / "notes.txt").write_text("not media", encoding="utf-8")
    (folder / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / "outside.mp4").write_bytes(b"outside the data folder")
    return folder


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    return TestClient(
        create_app(
            Settings(
                database_url="postgresql+psycopg://vfs:secret@db:5432/vfs", data_dir=str(data_dir)
            ),
            checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
            setting_store=MemorySettingStore(),
            provider_service=MemoryProviderService(),
            episode_service=MemoryEpisodeService(),
        )
    )


def not_found(response: object) -> bool:
    status = response.status_code  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    return bool(status == 404 and body["error"]["code"] == "not_found")


def test_a_video_is_served_whole_with_its_type_and_says_it_takes_ranges(client: TestClient) -> None:
    response = client.get(f"/api/v1/files/{VIDEO}")

    assert response.status_code == 200
    assert response.content == CONTENT
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "1024"


@pytest.mark.parametrize(
    ("asked", "status", "content_range", "body"),
    [
        ("bytes=100-199", 206, "bytes 100-199/1024", CONTENT[100:200]),
        ("bytes=1000-", 206, "bytes 1000-1023/1024", CONTENT[1000:]),
        ("bytes=-24", 206, "bytes 1000-1023/1024", CONTENT[1000:]),
        ("bytes=0-0", 206, "bytes 0-0/1024", CONTENT[:1]),
    ],
)
def test_a_range_request_gets_that_part_of_the_video(
    client: TestClient, asked: str, status: int, content_range: str, body: bytes
) -> None:
    response = client.get(f"/api/v1/files/{VIDEO}", headers={"Range": asked})

    assert response.status_code == status
    assert response.headers["content-range"] == content_range
    assert response.content == body
    assert response.headers["content-type"] == "video/mp4"


def test_a_range_past_the_end_is_refused_in_the_common_error_shape(client: TestClient) -> None:
    response = client.get(f"/api/v1/files/{VIDEO}", headers={"Range": "bytes=5000-6000"})

    assert response.status_code == 416
    assert response.json()["error"]["code"] == "range_not_satisfiable"
    assert response.headers["content-range"] == "bytes */1024"


@pytest.mark.parametrize("asked", ["bytes=abc", "pages=1-2", "bytes=9-3", "nonsense"])
def test_a_range_that_cannot_be_read_is_refused_in_the_common_error_shape(
    client: TestClient, asked: str
) -> None:
    response = client.get(f"/api/v1/files/{VIDEO}", headers={"Range": asked})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_range"


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("jobs/render.join/ab/abcdef/video_contact_sheet.jpg", "image/jpeg"),
        ("library/a_hill_dawn/v1.png", "image/png"),
        ("jobs/gen.voice/s01_hook.wav", "audio/wav"),
    ],
)
def test_pictures_and_narration_are_served_with_their_types(
    client: TestClient, path: str, media_type: str
) -> None:
    response = client.get(f"/api/v1/files/{path}")

    assert response.status_code == 200
    assert response.headers["content-type"] == media_type


@pytest.mark.parametrize(
    "path",
    [
        "../outside.mp4",
        "jobs/../../outside.mp4",
        "jobs/render.join/../../../outside.mp4",
        "%2e%2e/outside.mp4",
        "jobs/%2e%2e/%2e%2e/outside.mp4",
        "..%2foutside.mp4",
        "jobs\\..\\..\\outside.mp4",
        "..\\outside.mp4",
        "/outside.mp4",
        "//outside.mp4",
    ],
)
def test_nfr01_a_path_that_leaves_the_data_folder_is_not_found(
    client: TestClient, path: str
) -> None:
    assert not_found(client.get(f"/api/v1/files/{path}"))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../outside.mp4",
        "jobs/../../outside.mp4",
        "jobs/render.join/../../../outside.mp4",
        "jobs/../jobs/render.join/ab/abcdef/video.mp4",
        "./jobs/render.join/ab/abcdef/video.mp4",
        "jobs/./render.join/ab/abcdef/video.mp4",
        "jobs//render.join/ab/abcdef/video.mp4",
        "jobs\\render.join\\ab\\abcdef\\video.mp4",
        "..\\outside.mp4",
        "/jobs/render.join/ab/abcdef/video.mp4",
        "C:/Windows/win.ini",
        "C:video.mp4",
        "jobs/render.join/ab/abcdef/video.mp4\x00.txt",
        "jobs/render.join/ab/abcdef/video.mp4/",
    ],
)
def test_nfr01_the_path_check_itself_refuses_every_way_out(data_dir: Path, path: str) -> None:
    """A browser tidies `..` out of an address before it sends it. This asks the check
    directly, with the text as another client could send it."""
    with pytest.raises(ApiError) as refused:
        stored_file(data_dir, path)

    assert (refused.value.status_code, refused.value.code) == (404, "not_found")


def test_the_path_check_finds_a_stored_file(data_dir: Path) -> None:
    assert stored_file(data_dir, VIDEO) == (data_dir / VIDEO).resolve()


def test_nfr01_an_absolute_path_is_not_found(client: TestClient, tmp_path: Path) -> None:
    outside = (tmp_path / "outside.mp4").as_posix()

    assert not_found(client.get(f"/api/v1/files/{outside}"))
    assert not_found(client.get(f"/api/v1/files/{outside.lstrip('/')}"))


@pytest.mark.parametrize("path", ["notes.txt", ".env", "jobs", "jobs/render.join/ab/abcdef"])
def test_nfr01_only_media_files_are_served(client: TestClient, path: str) -> None:
    assert not_found(client.get(f"/api/v1/files/{path}"))


@pytest.mark.parametrize("path", ["missing.mp4", "jobs/render.join/zz/none/video.mp4"])
def test_a_file_that_does_not_exist_is_not_found(client: TestClient, path: str) -> None:
    assert not_found(client.get(f"/api/v1/files/{path}"))


def test_nfr01_a_link_that_points_out_of_the_data_folder_is_not_followed(
    client: TestClient, data_dir: Path, tmp_path: Path
) -> None:
    link = data_dir / "library" / "link.mp4"
    try:
        link.symlink_to(tmp_path / "outside.mp4")
    except OSError:
        pytest.skip("this machine does not let the test make a symbolic link")

    assert not_found(client.get("/api/v1/files/library/link.mp4"))


def test_the_address_of_a_stored_file_is_below_the_api_and_escapes_what_it_must() -> None:
    assert file_url(VIDEO) == f"{API_PREFIX}/files/{VIDEO}"
    assert file_url("library/a b/v1.png") == f"{API_PREFIX}/files/library/a%20b/v1.png"
    assert file_url(None) is None
