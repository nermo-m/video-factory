"""Settings read from environment variables and checked before a service starts.

Secrets come only from the environment (NFR-01). The database URL holds a password, so it
is kept out of repr() and must never be logged.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from packages.core.logs import LEVELS

PROVIDER_MODES = ("demo", "subscription", "api")
DEFAULT_COMFYUI_URL = "http://host.docker.internal:8188"
DEFAULT_CLI_BRIDGE_URL = "http://host.docker.internal:8189"
DEFAULT_KOKORO_MODEL_PATH = "/models/kokoro/kokoro.onnx"
DEFAULT_KOKORO_VOICES_PATH = "/models/kokoro/voices.bin"


class SettingsError(Exception):
    """One or more settings are missing or invalid. The message lists every problem."""


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    provider_mode: str = "demo"
    data_dir: str = "/data"
    cpu_workers: int = 2
    log_level: str = "info"
    comfyui_url: str = DEFAULT_COMFYUI_URL
    # The voice model files from `make models`. When they are missing the voice adapter
    # falls back to bundled sample audio, so a wrong path is not a start-up error.
    kokoro_model_path: str = DEFAULT_KOKORO_MODEL_PATH
    kokoro_voices_path: str = DEFAULT_KOKORO_VOICES_PATH
    # The critic agent reviews a video before the owner does (section 6.1). When it is off
    # the pipeline passes the critique state without a job.
    critic_enabled: bool = True
    # Subscription mode: where the host bridge to the command line tools listens
    # (section 3.4), and the model each tool is asked for. Empty leaves the choice to
    # the tool.
    cli_bridge_url: str = DEFAULT_CLI_BRIDGE_URL
    claude_cli_model: str = ""
    codex_cli_model: str = ""


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read and validate settings. Raises SettingsError listing everything that is wrong."""
    env = os.environ if environ is None else environ
    problems: list[str] = []

    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        problems.append(
            "DATABASE_URL is not set. In Docker it comes from docker-compose.yml. "
            "Outside Docker see .env.example."
        )

    provider_mode = env.get("PROVIDER_MODE", "demo").strip().lower() or "demo"
    if provider_mode not in PROVIDER_MODES:
        problems.append(f"PROVIDER_MODE must be one of {', '.join(PROVIDER_MODES)}.")

    cpu_workers = 2
    raw_workers = env.get("CPU_WORKERS", "2").strip()
    if raw_workers.isdecimal() and int(raw_workers) >= 1:
        cpu_workers = int(raw_workers)
    else:
        problems.append("CPU_WORKERS must be a whole number, 1 or more.")

    log_level = env.get("LOG_LEVEL", "info").strip().lower() or "info"
    if log_level not in LEVELS:
        problems.append(f"LOG_LEVEL must be one of {', '.join(LEVELS)}.")

    comfyui_url = env.get("COMFYUI_URL", "").strip() or DEFAULT_COMFYUI_URL
    parsed = urlsplit(comfyui_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        problems.append("COMFYUI_URL must be an http or https address.")

    cli_bridge_url = (env.get("CLI_BRIDGE_URL", "").strip() or DEFAULT_CLI_BRIDGE_URL).rstrip("/")
    parsed = urlsplit(cli_bridge_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        problems.append("CLI_BRIDGE_URL must be an http or https address.")

    critic = env.get("CRITIC_ENABLED", "true").strip().lower() or "true"
    if critic not in {"true", "false"}:
        problems.append("CRITIC_ENABLED must be true or false.")

    if problems:
        raise SettingsError("Invalid settings:\n- " + "\n- ".join(problems))

    return Settings(
        database_url=database_url,
        provider_mode=provider_mode,
        data_dir=env.get("DATA_DIR", "/data").strip() or "/data",
        cpu_workers=cpu_workers,
        log_level=log_level,
        comfyui_url=comfyui_url,
        kokoro_model_path=env.get("KOKORO_MODEL_PATH", "").strip() or DEFAULT_KOKORO_MODEL_PATH,
        kokoro_voices_path=env.get("KOKORO_VOICES_PATH", "").strip() or DEFAULT_KOKORO_VOICES_PATH,
        critic_enabled=critic == "true",
        cli_bridge_url=cli_bridge_url,
        claude_cli_model=env.get("CLAUDE_CLI_MODEL", "").strip(),
        codex_cli_model=env.get("CODEX_CLI_MODEL", "").strip(),
    )
