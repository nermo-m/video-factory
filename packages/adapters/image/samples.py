"""The demo twin of the picture adapter: bundled sample pictures (design doc section 3.3).

It returns the bundled picture with the asked asset id. Demo mode only ever plans the
sample episode, whose pictures all come from the library, so this adapter is rarely asked
at all. When it is asked for a picture it does not have, it still answers, with one of the
bundled pictures chosen by the asset id, so that demo mode never needs a key or a network.
"""

from __future__ import annotations

import hashlib
import time
from decimal import Decimal
from pathlib import Path

from packages.adapters.image.base import ImageRequest, ImageResult, png_size
from packages.core.enums import Provider
from packages.core.queue import NeedsOwnerError

DEFAULT_SAMPLES_DIR = (
    Path(__file__).resolve().parents[3] / "samples" / "lighthouse_keeper" / "assets"
)
MODEL = "bundled samples"


class SampleImages:
    """ImageAdapter that returns bundled pictures."""

    def __init__(self, folder: Path = DEFAULT_SAMPLES_DIR) -> None:
        self.folder = folder

    def create(self, request: ImageRequest) -> ImageResult:
        started = time.perf_counter()
        own = self.folder / f"{request.asset_id}.png"
        if own.is_file():
            chosen = own
        else:
            bundled = sorted(self.folder.glob("*.png"))
            if not bundled:
                raise NeedsOwnerError(
                    f"The bundled sample pictures are missing from {self.folder.name}. "
                    "They are part of the repository: check out the samples folder again."
                )
            # The same asset id always gets the same stand-in.
            digest = hashlib.sha256(request.asset_id.encode("utf-8")).digest()
            chosen = bundled[digest[0] % len(bundled)]
        data = chosen.read_bytes()
        size = png_size(data)
        if size is None:
            raise NeedsOwnerError(f"The bundled picture {chosen.name} is not a PNG file.")
        return ImageResult(
            data=data,
            width=size[0],
            height=size[1],
            provider=Provider.DEMO,
            model=MODEL,
            cost_usd=Decimal("0"),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
