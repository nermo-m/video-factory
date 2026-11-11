"""The worker process heartbeat, which the container health check reads."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from apps.worker import health
from apps.worker.main import run


def test_run_writes_a_heartbeat_and_stops_when_asked(tmp_path: Path) -> None:
    heartbeat = tmp_path / "nested" / "heartbeat"
    stop = threading.Event()
    thread = threading.Thread(target=run, args=(stop, heartbeat), kwargs={"interval_s": 0.01})

    thread.start()
    deadline = time.monotonic() + 5
    while not heartbeat.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    thread.join(timeout=5)

    assert heartbeat.exists()
    assert not thread.is_alive()


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
