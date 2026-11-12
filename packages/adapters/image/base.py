"""The picture interface (design doc section 3.3): a prompt in, one picture out.

One request is one picture. An adapter reports failures in the error classes the job queue
acts on (section 4.4): RetryableError, NeedsOwnerError, and PlanLimitError when a plan's
usage limit was reached.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from packages.core.enums import Provider

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class ImageRequest:
    asset_id: str
    prompt: str


@dataclass(frozen=True)
class ImageResult:
    """One picture as a complete PNG file, with what made it (FR-06)."""

    data: bytes
    width: int
    height: int
    provider: Provider
    model: str
    cost_usd: Decimal
    latency_ms: int
    seed: int | None = None


class ImageAdapter(Protocol):
    def create(self, request: ImageRequest) -> ImageResult:
        """Make one picture. Raises a JobError subclass when it cannot."""


def png_size(data: bytes) -> tuple[int, int] | None:
    """Width and height of a PNG file, or None when the bytes are not one."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return (width, height) if width > 0 and height > 0 else None
