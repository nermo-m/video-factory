"""Render the bundled sample episode, "The Lighthouse Keeper" (`make demo-render`).

    python -m apps.worker.demo_render --out /export/demo

This is the whole of milestone M1 in one command: the sample spec is checked, its
narration is spoken, the spec is resolved, the video is rendered scene by scene with its
sound, and the finished file is checked against the format of RN-01. It needs no keys, no
GPU and no accounts (FR-16). With the voice model from `make models` the narration is
spoken fresh. Without it the recordings bundled in `samples/voice/` are used.

The pipeline of milestone M2 does the same steps as queued jobs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.adapters.tts import TTSAdapter, VoiceError, create_tts_adapter
from packages.core import schemas
from packages.core.settings import DEFAULT_KOKORO_MODEL_PATH, DEFAULT_KOKORO_VOICES_PATH
from packages.render.audio import AudioError
from packages.render.compositor import RenderError
from packages.render.encode import EncodeError, for_preview, render_video
from packages.render.probe import ProbeError, format_problems, probe_video
from packages.render.resolver import AssetFile, NarrationTiming, ResolveError, resolve
from packages.render.theme import check_capabilities, load_theme

REPOSITORY = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPOSITORY / "samples" / "lighthouse_keeper"
VOICE_DIR = REPOSITORY / "samples" / "voice"
DEFAULT_WORKERS = 4


class DemoError(Exception):
    """The demo could not be rendered. The message says why."""


@dataclass(frozen=True)
class Prepared:
    """A sample that is ready to render: its resolved spec and the folder with its files."""

    resolved: dict[str, Any]
    storage: Path
    voice_engine: str  # "kokoro" when spoken now, "sample" when bundled recordings were used


@dataclass(frozen=True)
class DemoResult:
    video: Path
    contact_sheet: Path
    duration_s: float
    render_s: float
    voice_engine: str
    problems: list[str]


def load_sample() -> dict[str, Any]:
    """The authored spec of the sample episode."""
    loaded: dict[str, Any] = json.loads(
        (SAMPLE_DIR / "episode_spec.json").read_text(encoding="utf-8")
    )
    return loaded


def prepare(authored: Mapping[str, Any], tts: TTSAdapter, work: Path) -> Prepared:
    """Check the spec, copy its pictures, speak its narration and resolve it."""
    schemas.validate_or_raise("episode_spec", authored)
    theme = load_theme(authored["theme"])
    unfit = check_capabilities(authored, theme.capabilities)
    if unfit:
        raise DemoError("The theme cannot draw this spec:\n" + "\n".join(map(str, unfit)))

    storage = work / "storage"
    files: dict[str, AssetFile] = {}
    for asset in authored["assets"]:
        stored = f"library/{asset['id']}/v1.png"
        target = storage / stored
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SAMPLE_DIR / "assets" / f"{asset['id']}.png", target)
        files[asset["id"]] = AssetFile(file=stored, licence=asset.get("licence"))

    voice: dict[str, NarrationTiming] = {}
    engines: set[str] = set()
    for scene in authored["scenes"]:
        if not scene["narration"].strip():
            continue
        narration = tts.synthesise(
            scene["narration"],
            voice_id=authored["voice"]["voice_id"],
            speed=authored["voice"]["speed"],
        )
        stored = f"voice/{scene['id']}.wav"
        target = storage / stored
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(narration.wav)
        voice[scene["id"]] = NarrationTiming(stored, narration.duration_s, narration.words)
        engines.add(narration.engine)

    resolved = resolve(authored, voice, files)
    return Prepared(resolved, storage, voice_engine="+".join(sorted(engines)) or "none")


def render_demo(
    out: Path,
    *,
    tts: TTSAdapter | None = None,
    preview: bool = False,
    workers: int = DEFAULT_WORKERS,
) -> DemoResult:
    """Render the sample episode into `out` and check the finished file."""
    voice = tts or create_tts_adapter(
        Path(os.environ.get("KOKORO_MODEL_PATH", DEFAULT_KOKORO_MODEL_PATH)),
        Path(os.environ.get("KOKORO_VOICES_PATH", DEFAULT_KOKORO_VOICES_PATH)),
        samples_dir=VOICE_DIR,
    )
    out.mkdir(parents=True, exist_ok=True)
    prepared = prepare(load_sample(), voice, out)
    (out / "resolved_spec.json").write_text(
        json.dumps(prepared.resolved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    started = time.perf_counter()
    rendered = render_video(
        prepared.resolved,
        load_theme(prepared.resolved["theme"]),
        storage_root=prepared.storage,
        folder=out,
        preview=preview,
        workers=workers,
    )
    render_s = time.perf_counter() - started

    spec = for_preview(prepared.resolved) if preview else prepared.resolved
    problems = format_problems(probe_video(rendered.video), spec["format"], rendered.duration_s)
    return DemoResult(
        video=rendered.video,
        contact_sheet=rendered.contact_sheet,
        duration_s=rendered.duration_s,
        render_s=render_s,
        voice_engine=prepared.voice_engine,
        problems=problems,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the bundled sample episode.")
    parser.add_argument("--out", type=Path, required=True, help="folder for the result")
    parser.add_argument("--preview", action="store_true", help="540 by 960 at 15 fps")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    arguments = parser.parse_args(argv)

    try:
        result = render_demo(
            arguments.out, preview=arguments.preview, workers=max(1, arguments.workers)
        )
    except (
        DemoError,
        VoiceError,
        ResolveError,
        schemas.SchemaValidationError,
        RenderError,
        AudioError,
        EncodeError,
        ProbeError,
    ) as error:
        sys.stderr.write(f"The demo could not be rendered: {error}\n")
        return 1

    voice = {
        "kokoro": "spoken now by the Kokoro voice",
        "sample": "from the bundled recordings (run make models for the live voice)",
    }.get(result.voice_engine, result.voice_engine)
    sys.stdout.write(
        f"Video:          {result.video}\n"
        f"Contact sheet:  {result.contact_sheet}\n"
        f"Length:         {result.duration_s:.1f} seconds\n"
        f"Narration:      {voice}\n"
        f"Render time:    {result.render_s:.0f} seconds with {arguments.workers} worker(s)\n"
    )
    if result.problems:
        sys.stderr.write("Format checks failed:\n" + "\n".join(result.problems) + "\n")
        return 1
    sys.stdout.write("Format checks:  passed (RN-01)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
