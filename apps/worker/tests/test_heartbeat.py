"""The worker process heartbeat file, which the container health check reads."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from apps.worker import health
from apps.worker.main import heartbeat_path


def test_health_passes_with_a_fresh_heartbeat(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    heartbeat.touch()

    assert health.is_healthy(heartbeat, max_age_s=30) is True
    assert health.main(["--file", str(heartbeat)]) == 0


def test_health_fails_with_a_stale_heartbeat(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    heartbeat.touch()
    old = time.time() - 120
    os.utime(heartbeat, (old, old))

    assert health.is_healthy(heartbeat, max_age_s=30) is False
    assert health.main(["--file", str(heartbeat)]) == 1


def test_health_fails_without_a_heartbeat(tmp_path: Path) -> None:
    assert health.is_healthy(tmp_path / "missing", max_age_s=30) is False


def test_heartbeat_location_can_be_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKER_HEARTBEAT_FILE", str(tmp_path / "beat"))
    assert heartbeat_path() == tmp_path / "beat"

    monkeypatch.delenv("WORKER_HEARTBEAT_FILE")
    assert heartbeat_path().name == "vfs-worker-heartbeat"
