"""Static checks on docker-compose.release.yml, the file a visitor runs from a release.

It must start the same four services as the development file from published images,
with nothing to build, and keep every port on 127.0.0.1 (NFR-02).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGE_PREFIX = "ghcr.io/nermo-m/video-factory-"


def load(name: str) -> dict[str, Any]:
    loaded = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def release() -> dict[str, Any]:
    return load("docker-compose.release.yml")


@pytest.fixture(scope="module")
def development() -> dict[str, Any]:
    return load("docker-compose.yml")


def test_release_runs_the_same_four_services(
    release: dict[str, Any], development: dict[str, Any]
) -> None:
    assert sorted(release["services"]) == sorted(development["services"])


def test_release_uses_published_images_and_builds_nothing(release: dict[str, Any]) -> None:
    for name in ("web", "api", "worker"):
        service = release["services"][name]
        assert "build" not in service, f"{name} must not be built from source in a release"
        assert service["image"] == f"{IMAGE_PREFIX}{name}:${{VFS_VERSION:-latest}}"
    assert release["services"]["db"]["image"].startswith("postgres:16")


def test_nfr02_release_ports_bind_to_loopback(release: dict[str, Any]) -> None:
    published = [
        str(port) for service in release["services"].values() for port in service.get("ports", [])
    ]

    assert published
    assert all(port.startswith("127.0.0.1:") for port in published)


def test_release_keeps_health_checks_start_order_and_volumes(
    release: dict[str, Any], development: dict[str, Any]
) -> None:
    for name, service in release["services"].items():
        dev = development["services"][name]
        assert service["healthcheck"]["test"] == dev["healthcheck"]["test"]
        assert service["restart"] == "unless-stopped"
        assert service.get("depends_on") == dev.get("depends_on")
        assert service.get("volumes") == dev.get("volumes")
    assert set(release["volumes"]) == set(development["volumes"])


def test_release_defaults_to_demo_mode_and_needs_no_secret_but_the_database_password(
    release: dict[str, Any],
) -> None:
    for name in ("api", "worker"):
        assert release["services"][name]["environment"]["PROVIDER_MODE"] == "${PROVIDER_MODE:-demo}"
    password = release["services"]["db"]["environment"]["POSTGRES_PASSWORD"]
    assert password.startswith("${POSTGRES_PASSWORD:?")


def test_release_workflow_publishes_the_images_the_compose_file_pulls() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "ghcr.io/${{ github.repository }}-${{ matrix.service }}" in workflow
    assert "service: [web, api, worker]" in workflow
