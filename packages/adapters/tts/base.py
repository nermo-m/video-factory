"""The voice interface (design doc section 3.3): narration text in, audio and word timings out.

Narration is synthesised one scene at a time, as a single passage (section 7.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from packages.render.resolver import WordTiming


class VoiceError(Exception):
    """The narration could not be made. The message says what the owner can do about it."""


@dataclass(frozen=True)
class Narration:
    """The voice for one scene."""

    wav: bytes  # a complete WAV file: mono, 16-bit
    sample_rate: int
    duration_s: float
    words: list[WordTiming]  # one per whitespace-separated word of the narration
    engine: str  # "kokoro" for the real voice, "sample" for bundled audio


class TTSAdapter(Protocol):
    def synthesise(
        self,
        text: str,
        *,
        voice_id: str,
        speed: float = 1.0,
        pronunciation: Mapping[str, str] | None = None,
    ) -> Narration:
        """Speak one scene's narration. Raises VoiceError when it cannot."""
