"""Container health check for the worker: python -m apps.worker.health

Healthy means the worker touched its heartbeat file recently.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from pathlib import Path

from apps.worker.main import heartbeat_path

MAX_AGE_S = 30.0


def is_healthy(heartbeat: Path, *, max_age_s: float) -> bool:
    try:
        age = time.time() - heartbeat.stat().st_mtime
    except FileNotFoundError:
        return False
    return age <= max_age_s


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker health check")
    parser.add_argument("--file", type=Path, default=None, help="heartbeat file to read")
    parser.add_argument("--max-age", type=float, default=MAX_AGE_S, help="seconds")
    args = parser.parse_args(argv)
    heartbeat: Path = args.file if args.file is not None else heartbeat_path()
    return 0 if is_healthy(heartbeat, max_age_s=args.max_age) else 1


if __name__ == "__main__":
    raise SystemExit(main())
