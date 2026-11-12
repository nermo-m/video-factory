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
        cli_bridge_url="http://host.docker.internal:8189",
        claude_cli_model="",
        codex_cli_model="",
        limit_check_minutes=10,
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


def test_fr34_settings_read_how_often_the_limits_are_checked() -> None:
    assert load_settings({**BASE_ENV, "LIMIT_CHECK_MINUTES": "3"}).limit_check_minutes == 3
    with pytest.raises(SettingsError, match="LIMIT_CHECK_MINUTES must be a whole number"):
        load_settings({**BASE_ENV, "LIMIT_CHECK_MINUTES": "0"})


def test_fr27_settings_read_where_the_bridge_is_and_which_models_it_is_asked_for() -> None:
    settings = load_settings(
        {
            **BASE_ENV,
            "CLI_BRIDGE_URL": " http://host.docker.internal:9001/ ",
            "CLAUDE_CLI_MODEL": " claude-opus-5-5 ",
            "CODEX_CLI_MODEL": "gpt-5.5",
        }
    )

    assert settings.cli_bridge_url == "http://host.docker.internal:9001"
    assert settings.claude_cli_model == "claude-opus-5-5"
    assert settings.codex_cli_model == "gpt-5.5"


@pytest.mark.parametrize("url", ["ftp://host:8189", "host.docker.internal:8189", "http://"])
def test_a_bridge_address_that_is_not_an_http_address_is_refused(url: str) -> None:
    with pytest.raises(SettingsError, match="CLI_BRIDGE_URL must be an http or https address"):
        load_settings({**BASE_ENV, "CLI_BRIDGE_URL": url})


def test_nfr01_settings_never_print_the_database_password() -> None:
    settings = load_settings(BASE_ENV)

    assert "secret" not in repr(settings)
    assert "secret" not in str(settings)


def test_token_counts_are_logged_as_numbers_while_tokens_stay_hidden() -> None:
    log = logging.getLogger("test.tokens")

    (entry,) = emit(
        "info",
        log,
        "info",
        "model call",
        extra={"input_tokens": 1200, "output_tokens": 340, "access_token": "abc", "token": "xyz"},
    )

    assert (entry["input_tokens"], entry["output_tokens"]) == (1200, 340)
    assert entry["access_token"] == logs.REDACTED
    assert entry["token"] == logs.REDACTED
