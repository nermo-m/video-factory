"""Static checks on docker-compose.yml.

NFR-02: all services bind to 127.0.0.1. D2: four services (web, api, worker, db).
D3: containers reach the Windows host at host.docker.internal. D9: data lives in volumes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("web", "api", "worker", "db")


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_d2_defines_exactly_the_four_services(compose: dict[str, Any]) -> None:
    assert sorted(compose["services"]) == sorted(SERVICES)


def test_nfr02_every_published_port_binds_to_loopback(compose: dict[str, Any]) -> None:
    published = [
        (name, str(port))
        for name, service in compose["services"].items()
        for port in service.get("ports", [])
    ]

    assert published, "web and api must be reachable from the host"
    for name, port in published:
        assert port.startswith("127.0.0.1:"), f"{name} publishes {port} beyond 127.0.0.1"


def test_nfr02_no_service_uses_host_networking(compose: dict[str, Any]) -> None:
    for name, service in compose["services"].items():
        assert service.get("network_mode") != "host", f"{name} must not use the host network"


@pytest.mark.parametrize("name", SERVICES)
def test_every_service_has_a_health_check_and_restarts(compose: dict[str, Any], name: str) -> None:
    service = compose["services"][name]

    assert service["healthcheck"]["test"], f"{name} needs a health check"
    assert service["restart"] == "unless-stopped"


@pytest.mark.parametrize("name", ["api", "worker"])
def test_d3_host_gateway_is_mapped(compose: dict[str, Any], name: str) -> None:
    assert "host.docker.internal:host-gateway" in compose["services"][name]["extra_hosts"]


def test_d9_data_lives_only_in_named_volumes(compose: dict[str, Any]) -> None:
    named = set(compose["volumes"])
    assert {"db-data", "app-data"} <= named

    for name, service in compose["services"].items():
        for mount in service.get("volumes", []):
            source = str(mount).split(":", 1)[0]
            assert source in named, f"{name} mounts {source}, which is not a named volume"

    assert "db-data:/var/lib/postgresql/data" in compose["services"]["db"]["volumes"]
    for name in ("api", "worker"):
        assert "app-data:/data" in compose["services"][name]["volumes"]


def test_services_start_in_dependency_order(compose: dict[str, Any]) -> None:
    services = compose["services"]

    assert services["api"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["worker"]["depends_on"]["db"]["condition"] == "service_healthy"
    # The api applies migrations before it reports healthy, so the worker waits for it.
    assert services["worker"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_nfr01_compose_holds_no_password_default(compose: dict[str, Any]) -> None:
    password = compose["services"]["db"]["environment"]["POSTGRES_PASSWORD"]

    assert password.startswith("${POSTGRES_PASSWORD:?"), "the password must come from .env"


def test_provider_mode_defaults_to_demo(compose: dict[str, Any]) -> None:
    for name in ("api", "worker"):
        assert compose["services"][name]["environment"]["PROVIDER_MODE"] == "${PROVIDER_MODE:-demo}"
