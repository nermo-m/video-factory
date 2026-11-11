"""The no-op job: proves that a job travels through the queue and the worker."""

from __future__ import annotations

from typing import Any

from apps.worker.runner import JobContext


def noop(context: JobContext) -> dict[str, Any]:
    return {"echo": context.job.input, "output_path": str(context.output_path)}
