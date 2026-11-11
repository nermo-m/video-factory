"""Write the OpenAPI document that the web client is generated from.

python -m apps.api.openapi           write apps/api/openapi.json
python -m apps.api.openapi --check   exit 1 when the committed file is out of date
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from packages.core.settings import Settings

OPENAPI_PATH = Path(__file__).resolve().parent / "openapi.json"


def render_openapi() -> str:
    """The OpenAPI document as stable, sorted JSON text."""

    def unused() -> Check:
        return Check(status=CheckStatus.OK)

    # The document depends only on the routes, so placeholder settings and checks are enough
    # and nothing is contacted.
    settings = Settings(database_url="postgresql+psycopg://unused:unused@unused/unused")
    app = create_app(settings, checks=HealthChecks(database=unused, storage=unused, comfyui=unused))
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    rendered = render_openapi()
    if "--check" in arguments:
        current = OPENAPI_PATH.read_text(encoding="utf-8") if OPENAPI_PATH.exists() else ""
        if current != rendered:
            sys.stderr.write("apps/api/openapi.json is out of date. Run: make generate-api\n")
            return 1
        return 0
    OPENAPI_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {OPENAPI_PATH}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
