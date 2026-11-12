"""Pictures in subscription mode: Codex's image tool through the host bridge (FR-30).

Design doc section 3.4. The Codex command line tool is signed in on the owner's PC with
their ChatGPT plan. The worker asks the bridge (`tools/cli_bridge`, `POST /codex/image`)
for one picture at a time and gets the finished PNG back.

* A picture is covered by the plan: cost 0, billing type `plan` (FR-29).
* A usage limit comes back as `plan_limit` and becomes PlanLimitError with the reset time.
  The job then waits. Nothing here can reach a paid API (FR-28).
* The adapter exists in subscription mode only and refuses to be built in another mode.
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
from decimal import Decimal

from packages.adapters.image.base import ImageRequest, ImageResult, png_size
from packages.adapters.llm.cli_bridge import GRACE_S, QUEUE_S, BridgeClient
from packages.core.enums import Provider

logger = logging.getLogger(__name__)

# Seconds for one picture. A picture took 43 seconds when this was measured (ADR 10).
IMAGE_TIMEOUT_S = 600.0
MODEL = "codex image tool"


class CodexImages(BridgeClient):
    """ImageAdapter for subscription mode: Codex on the owner's ChatGPT plan."""

    title = "Codex"

    def __init__(
        self,
        *,
        mode: str,
        bridge_url: str,
        model: str | None = None,
        timeout_s: float = IMAGE_TIMEOUT_S,
        queue_s: float = QUEUE_S,
        grace_s: float = GRACE_S,
    ) -> None:
        super().__init__(
            mode=mode,
            bridge_url=bridge_url,
            model=model,
            timeout_s=timeout_s,
            queue_s=queue_s,
            grace_s=grace_s,
        )

    def create(self, request: ImageRequest) -> ImageResult:
        started = time.perf_counter()
        body: dict[str, object] = {"prompt": request.prompt, "timeout_s": self.timeout_s}
        if self.model is not None:
            body["model"] = self.model
        answer = self._post("codex/image", body)

        encoded = answer.get("image_base64")
        try:
            data = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) else b""
        except (binascii.Error, ValueError):
            data = b""
        size = png_size(data)
        if size is None:
            raise self._not_the_bridge()

        result = ImageResult(
            data=data,
            width=size[0],
            height=size[1],
            provider=Provider.CHATGPT_PLAN,
            # The tool does not say which image model it used.
            model=MODEL,
            # Covered by the owner's plan.
            cost_usd=Decimal("0"),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        # Numbers only: never the prompt.
        logger.info(
            "picture made",
            extra={
                "provider": result.provider.value,
                "model": result.model,
                "asset_id": request.asset_id,
                "width": result.width,
                "height": result.height,
                "bytes": len(data),
                "latency_ms": result.latency_ms,
            },
        )
        return result
