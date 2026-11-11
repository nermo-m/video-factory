"""Run the API: python -m apps.api

Binds to 127.0.0.1 unless API_HOST says otherwise. The container image sets API_HOST to
0.0.0.0, which is inside the container only: docker-compose.yml publishes the port on the
host's 127.0.0.1 (NFR-02).
"""

from __future__ import annotations

import os
import sys

import uvicorn

from packages.core.logs import configure_logging
from packages.core.settings import SettingsError, load_settings


def main() -> int:
    try:
        settings = load_settings()
    except SettingsError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    configure_logging(settings.log_level)
    uvicorn.run(
        "apps.api.main:create_app",
        factory=True,
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8000")),
        # Uvicorn's records go through the JSON formatter set up above (NFR-03).
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
