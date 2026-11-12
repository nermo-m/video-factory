"""Record the sample episode's narration with the real voice (`make sample-voice`).

The recordings are stored in samples/voice/ and committed, so the demo can run on a
machine that does not have the 354 MB voice model (FR-16). Run this again whenever the
narration, the voice or the speed of the sample spec changes. It needs the model files
from `make models` and espeak-ng, so it runs inside the worker image.

Recordings that no longer belong to a scene are removed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from apps.worker.demo_render import VOICE_DIR, load_sample
from packages.adapters.tts import TTSAdapter, VoiceError, create_tts_adapter
from packages.adapters.tts.samples import write_sample
from packages.core.settings import DEFAULT_KOKORO_MODEL_PATH, DEFAULT_KOKORO_VOICES_PATH


def record(tts: TTSAdapter, folder: Path = VOICE_DIR) -> list[Path]:
    """Speak every scene of the sample and store the recordings. Returns the files."""
    authored = load_sample()
    voice_id, speed = authored["voice"]["voice_id"], authored["voice"]["speed"]
    written: list[Path] = []
    for scene in authored["scenes"]:
        if not scene["narration"].strip():
            continue
        narration = tts.synthesise(scene["narration"], voice_id=voice_id, speed=speed)
        if narration.engine != "kokoro":
            raise VoiceError(
                "The sample narration must be recorded with the real voice. "
                "Download the model first with: make models"
            )
        written.append(
            write_sample(folder, narration, text=scene["narration"], voice_id=voice_id, speed=speed)
        )
    for stale in set(folder.glob("*.wav")) - set(written):
        stale.unlink()
    return written


def main() -> int:
    tts = create_tts_adapter(
        Path(os.environ.get("KOKORO_MODEL_PATH", DEFAULT_KOKORO_MODEL_PATH)),
        Path(os.environ.get("KOKORO_VOICES_PATH", DEFAULT_KOKORO_VOICES_PATH)),
        samples_dir=VOICE_DIR,
    )
    try:
        written = record(tts)
    except VoiceError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    for path in written:
        sys.stdout.write(f"recorded {path.name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
