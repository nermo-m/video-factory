"""Structured JSON logs (NFR-03) and secret-free settings (NFR-01)."""

from __future__ import annotations

import io
import json
import logging
import uuid

import pytest

from packages.core import logs
from packages.core.settings import Settings, SettingsError, load_settings


def emit(
    configure_level: str, log: logging.Logger, call: str, *args: object, **kwargs: object
) -> list[dict[str, object]]:
    stream = io.StringIO()
    logs.configure_logging(configure_level, stream=stream)
    try:
        getattr(log, call)(*args, **kwargs)
    finally:
        logs.configure_logging("info")
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_nfr03_logs_are_json_lines_with_job_and_episode_ids() -> None:
    job_id, episode_id = uuid.uuid4(), uuid.uuid4()

    [record] = emit(
        "info",
        logging.getLogger("apps.worker"),
        "info",
        "job %s finished",
        "noop",
        extra={"job_id": job_id, "episode_id": episode_id, "duration_ms": 12},
    )

    assert record["message"] == "job noop finished"
    assert record["level"] == "info"
    assert record["logger"] == "apps.worker"
    assert record["job_id"] == str(job_id)
    assert record["episode_id"] == str(episode_id)
    assert record["duration_ms"] == 12
    assert str(record["time"]).endswith("+00:00")


def test_nfr03_exceptions_carry_the_stack_trace() -> None:
    log = logging.getLogger("apps.worker")
    stream = io.StringIO()
    logs.configure_logging("info", stream=stream)
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("job failed", extra={"job_id": "j1"})
    finally:
        logs.configure_logging("info")

    record = json.loads(stream.getvalue())
    assert record["level"] == "error"
    assert "ValueError: boom" in record["exception"]
    assert "Traceback" in record["exception"]


def test_nfr03_level_filters_records() -> None:
    assert emit("warning", logging.getLogger("apps.worker"), "info", "quiet") == []


def test_nfr01_secret_looking_fields_are_never_logged() -> None:
    [record] = emit(
        "info",
        logging.getLogger("apps.api"),
        "info",
        "settings loaded",
        extra={
            "api_key": "sk-live-123",
            "app_password": "hunter2",
            "database_url": "postgresql://u:p@h/d",
            "provider_mode": "demo",
        },
    )

    assert record["api_key"] == logs.REDACTED
    assert record["app_password"] == logs.REDACTED
    assert record["database_url"] == logs.REDACTED
    assert record["provider_mode"] == "demo"
    assert "sk-live-123" not in json.dumps(record)


BASE_ENV = {"DATABASE_URL": "postgresql+psycopg://vfs:secret@db:5432/vfs"}


def test_settings_have_the_documented_defaults() -> None:
    settings = load_settings(BASE_ENV)

    assert settings == Settings(
        database_url="postgresql+psycopg://vfs:secret@db:5432/vfs",
        provider_mode="demo",
        data_dir="/data",
        cpu_workers=2,
        log_level="info",
        comfyui_url="http://host.docker.internal:8188",
        kokoro_model_path="/models/kokoro/kokoro.onnx",
        kokoro_voices_path="/models/kokoro/voices.bin",
        critic_enabled=True,
    )


@pytest.mark.parametrize(
    ("written", "expected"), [("false", False), ("FALSE", False), ("true", True), (" True ", True)]
)
def test_the_critic_can_be_switched_off(written: str, expected: bool) -> None:
    assert load_settings({**BASE_ENV, "CRITIC_ENABLED": written}).critic_enabled is expected


def test_a_critic_switch_that_is_neither_true_nor_false_is_refused() -> None:
    with pytest.raises(SettingsError, match="CRITIC_ENABLED must be true or false"):
        load_settings({**BASE_ENV, "CRITIC_ENABLED": "maybe"})


def test_settings_read_where_the_voice_model_files_are() -> None:
    settings = load_settings(
        {
            **BASE_ENV,
            "KOKORO_MODEL_PATH": " /srv/models/kokoro.onnx ",
            "KOKORO_VOICES_PATH": "/srv/models/voices.bin",
        }
    )

    assert settings.kokoro_model_path == "/srv/models/kokoro.onnx"
    assert settings.kokoro_voices_path == "/srv/models/voices.bin"


def test_settings_read_the_environment() -> None:
    settings = load_settings(
        {
            **BASE_ENV,
            "PROVIDER_MODE": "subscription",
            "CPU_WORKERS": "4",
            "LOG_LEVEL": "DEBUG",
            "DATA_DIR": "/srv/data",
        }
    )

    assert (
        settings.provider_mode,
        settings.cpu_workers,
        settings.log_level,
        settings.data_dir,
    ) == (
        "subscription",
        4,
        "debug",
        "/srv/data",
    )


def test_settings_report_every_problem_at_once() -> None:
    with pytest.raises(SettingsError) as raised:
        load_settings(
            {
                "PROVIDER_MODE": "paid",
                "CPU_WORKERS": "zero",
                "LOG_LEVEL": "loud",
                "COMFYUI_URL": "file:///etc/passwd",
            }
        )

    message = str(raised.value)
    assert "DATABASE_URL is not set" in message
    assert "PROVIDER_MODE must be one of demo, subscription, api" in message
    assert "CPU_WORKERS must be a whole number, 1 or more" in message
    assert "LOG_LEVEL must be one of debug, info, warning, error" in message
    assert "COMFYUI_URL must be an http or https address" in message


def test_nfr01_settings_never_print_the_database_password() -> None:
    settings = load_settings(BASE_ENV)

    assert "secret" not in repr(settings)
    assert "secret" not in str(settings)
