"""Reachability probe for ComfyUI on the host (design doc section 8, step 1).

Only "does it answer" is decided here. The full ComfyUI client arrives with the clip
adapter. The endpoint name comes from the design document and must be confirmed against
the owner's installed ComfyUI before that client is written (risk R2).
"""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request
from urllib.parse import urlsplit

SYSTEM_STATS_PATH = "/system_stats"


def comfyui_reachable(base_url: str, *, timeout_s: float = 1.5) -> bool:
    """True when ComfyUI answers its system stats endpoint with HTTP 200."""
    if urlsplit(base_url).scheme not in {"http", "https"}:
        return False
    url = base_url.rstrip("/") + SYSTEM_STATS_PATH
    try:
        # The scheme is checked above, so this cannot open a file or another scheme.
        with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310
            return bool(response.status == 200)
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ValueError):
        # Nothing listening, a timeout, or something on that port that does not speak HTTP.
        return False
