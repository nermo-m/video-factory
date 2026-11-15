"""What a clip adapter takes and gives back (design doc sections 3.4 and 8, FR-07).

A clip is a short moving picture made from one still picture and a few words about what
moves. The open model behind it makes at most about five seconds at a time, so a longer
scene is made in pieces: each piece starts from the last frame of the one before. That is
why a result carries its last frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

# Wan 2.2 makes 16 frames a second, and its frame counts are four times a whole number
# plus one. 81 frames (five seconds) is the most one piece holds.
CLIP_FPS = 16.0
MIN_FRAMES = 17
MAX_FRAMES = 81


def wan_frames(seconds: float) -> int:
    """The frame count of one piece that is at least this long, within what a piece holds."""
    wanted = math.ceil(seconds * CLIP_FPS - 1e-9)
    stepped = 4 * math.ceil(max(wanted - 1, 0) / 4) + 1
    return min(MAX_FRAMES, max(MIN_FRAMES, stepped))


@dataclass(frozen=True)
class ClipRequest:
    # A name for the uploaded picture. Only letters, digits, dashes and underscores of it
    # are used.
    name: str
    # The start picture, as a PNG or JPEG file.
    picture: bytes
    # What moves and how, in words.
    prompt: str
    frames: int
    seed: int
    width: int = 480
    height: int = 832


@dataclass(frozen=True)
class ClipResult:
    # The clip as an MP4 file.
    video: bytes
    # Its last frame as a PNG file: the start picture of the next piece.
    last_frame: bytes
    frames: int
    fps: float
    width: int
    height: int
    model: str
    latency_ms: int


class ClipAdapter(Protocol):
    def create(self, request: ClipRequest) -> ClipResult:
        """Make one piece of a clip. Raises the job queue's errors."""
        ...

    def release(self) -> None:
        """Give the graphics card's memory back when no more clips are waiting."""
        ...
