"""Clip adapters: the interface and Wan 2.2 through ComfyUI on the owner's PC
(design doc sections 3.4 and 8)."""

from packages.adapters.clip.base import (
    CLIP_FPS,
    MAX_FRAMES,
    ClipAdapter,
    ClipRequest,
    ClipResult,
    wan_frames,
)
from packages.adapters.clip.comfyui import ComfyClips

__all__ = [
    "CLIP_FPS",
    "MAX_FRAMES",
    "ClipAdapter",
    "ClipRequest",
    "ClipResult",
    "ComfyClips",
    "wan_frames",
]
