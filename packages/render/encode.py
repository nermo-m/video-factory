"""Encode: frames to scene files, scene files to a video (design doc section 7).

* Each scene is drawn frame by frame and piped to FFmpeg as raw pixels. It becomes its own
  H.264 file, and every scene file uses the same encoder settings (RN-02).
* The scene files are joined without re-encoding, and the audio mix is added as AAC with
  the index at the front of the file ("faststart", RN-01). Transitions need nothing here:
  they are drawn inside the outgoing and the incoming scene (RN-03).
* A scene file is named after a key, a hash of everything that can change its pixels.
  Rendering again encodes only scenes whose key changed (RN-04, FR-12).
* Files are written under a temporary name and renamed when they are complete, so a file
  with a final name is always a finished file (RN-05).
* Preview mode is the same spec at 540 by 960 and 15 frames a second (RN-12).

FFmpeg is started as a separate program, with an argument list and no shell.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from packages.render import compositor as compositor_module
from packages.render import primitives, text
from packages.render.audio import mix_audio
from packages.render.compositor import Compositor, scene_frame_counts
from packages.render.contact_sheet import contact_sheet
from packages.render.primitives import ClipFrames
from packages.render.theme import Theme
from packages.render.wav import write_wav

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
PREVIEW_FORMAT = {"width": 540, "height": 960, "fps": 15}
AUDIO_BITRATE = "192k"
_KEY_LENGTH = 16
_QUIET = ["-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
# Shared by every scene file, so the files can be joined by copying (RN-02). The picture
# is converted to the BT.709 colours that players assume for HD video.
_VIDEO_ARGS = [
    "-an",
    "-vf",
    "scale=in_range=full:out_range=tv:out_color_matrix=bt709",
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "18",
    "-pix_fmt",
    "yuv420p",
    "-colorspace",
    "bt709",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-color_range",
    "tv",
]
_ENGINE_SOURCES = (compositor_module, primitives, text)
_MAX_CLIP_FRAMES = 600

# Draws and encodes one scene into the given file: (resolved, theme, index, path, storage).
SceneEncoder = Callable[[Mapping[str, Any], Theme, int, Path, Path | None], None]


class EncodeError(Exception):
    """A video file could not be made. The message carries what FFmpeg said."""


@dataclass(frozen=True)
class SceneFile:
    """One scene's video file."""

    index: int
    scene_id: str
    key: str
    path: Path
    frames: int
    reused: bool  # true when the file was already there and nothing was encoded


@dataclass(frozen=True)
class RenderResult:
    video: Path
    audio: Path
    contact_sheet: Path
    scenes: list[SceneFile]
    duration_s: float
    preview: bool

    @property
    def encoded(self) -> list[str]:
        """The ids of the scenes that were encoded in this run."""
        return [scene.scene_id for scene in self.scenes if not scene.reused]


# --- what needs encoding ---------------------------------------------------------------


def for_preview(resolved: Mapping[str, Any]) -> dict[str, Any]:
    """The same spec in preview size: 540 by 960 at 15 frames a second (RN-12)."""
    return {**resolved, "format": {**resolved["format"], **PREVIEW_FORMAT}}


def _fingerprint(paths: Iterable[Path]) -> str:
    """A hash of the contents of some files. A missing file counts as its own value."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def scene_keys(resolved: Mapping[str, Any], theme: Theme, storage_root: Path | None) -> list[str]:
    """One key per scene: a hash of everything that can change the scene's pixels.

    That is the scene itself, the transition coming in from the scene before, the format,
    the seed, the picture or clip it shows, the claim behind a statistic, every file of the
    theme and the drawing code. Times in a resolved spec are absolute, so a scene that
    starts later than before has a new key too: its drifting background is at a different
    point of its motion.
    """
    engine = _fingerprint(Path(str(module.__file__)) for module in _ENGINE_SOURCES)
    look = _fingerprint(
        path
        for path in sorted(theme.root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    )
    assets = {asset["id"]: asset for asset in resolved["assets"]}
    claims = {claim["id"]: claim for claim in resolved["claims"]}
    scenes = resolved["scenes"]

    keys: list[str] = []
    for index, scene in enumerate(scenes):
        asset = assets.get(scene["visual"]["asset_id"]) if "visual" in scene else None
        files = [
            storage_root / asset[name]
            for name in ("file", "clip_file")
            if asset and storage_root and asset.get(name)
        ]
        content = {
            "engine": engine,
            "theme": look,
            "format": resolved["format"],
            "seed": resolved["seed"],
            "scene": scene,
            "transition_in": scenes[index - 1].get("transition_out") if index else None,
            "asset": asset,
            "asset_files": _fingerprint(files),
            "claim": claims.get(scene["stat"]["claim_id"]) if "stat" in scene else None,
        }
        packed = json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
        keys.append(hashlib.sha256(packed).hexdigest()[:_KEY_LENGTH])
    return keys


def _finish(
    encode: SceneEncoder,
    resolved: Mapping[str, Any],
    theme: Theme,
    index: int,
    storage_root: Path | None,
    final: Path,
) -> None:
    """Encode one scene into a temporary name and rename it on success (RN-05)."""
    partial = final.with_name(f"{final.stem}.partial.mp4")
    try:
        encode(resolved, theme, index, partial, storage_root)
        partial.replace(final)
    finally:
        partial.unlink(missing_ok=True)


def render_scenes(
    resolved: Mapping[str, Any],
    theme: Theme,
    *,
    storage_root: Path | None,
    folder: Path,
    workers: int = 1,
    encode: SceneEncoder | None = None,
) -> list[SceneFile]:
    """Make sure every scene has its file. Scenes whose file exists are not encoded again.

    With more than one worker the scenes are encoded in separate processes. A script that
    calls this then needs the usual `if __name__ == "__main__":` guard.
    """
    encoder = encode or encode_scene
    folder.mkdir(parents=True, exist_ok=True)
    counts = scene_frame_counts(resolved)
    files: list[SceneFile] = []
    for index, (scene, key) in enumerate(
        zip(resolved["scenes"], scene_keys(resolved, theme, storage_root), strict=True)
    ):
        path = folder / f"scene_{index:02d}_{scene['id']}_{key}.mp4"
        files.append(SceneFile(index, scene["id"], key, path, counts[index], reused=path.is_file()))

    missing = [file for file in files if not file.reused]
    if workers > 1 and len(missing) > 1:
        # Fresh processes, the same way on every system. A forked copy of a process
        # that has threads can hang.
        fresh = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=fresh) as pool:
            running = [
                pool.submit(_finish, encoder, resolved, theme, file.index, storage_root, file.path)
                for file in missing
            ]
            for future in running:
                future.result()
    else:
        for file in missing:
            _finish(encoder, resolved, theme, file.index, storage_root, file.path)
    return files


# --- FFmpeg ----------------------------------------------------------------------------


def _run(command: list[str], *, what: str) -> subprocess.CompletedProcess[bytes]:
    try:
        # A fixed program name and an argument list, no shell.
        return subprocess.run(command, capture_output=True, check=True)  # noqa: S603
    except FileNotFoundError as error:
        raise EncodeError(
            f"{command[0]} is not installed. It is part of the worker image: render inside "
            "the worker container, or install FFmpeg on this machine."
        ) from error
    except subprocess.CalledProcessError as error:
        said = error.stderr.decode("utf-8", errors="replace").strip()[-800:]
        raise EncodeError(f"FFmpeg could not {what}: {said}") from error


def encode_scene(
    resolved: Mapping[str, Any],
    theme: Theme,
    index: int,
    path: Path,
    storage_root: Path | None,
) -> None:
    """Draw one scene and encode it as an H.264 file without sound."""
    scene = resolved["scenes"][index]
    clips: dict[str, ClipFrames] = {}
    if scene.get("visual", {}).get("clip"):
        asset_id = scene["visual"]["asset_id"]
        asset = next(item for item in resolved["assets"] if item["id"] == asset_id)
        if asset.get("clip_file") and storage_root is not None:
            clips[asset_id] = load_clip(storage_root / asset["clip_file"])
    drawing = Compositor(resolved, theme, storage_root=storage_root, clips=clips)
    width, height = drawing.size
    command = [
        FFMPEG,
        *_QUIET[:-2],
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(drawing.fps),
        "-i",
        "-",
        *_VIDEO_ARGS,
        str(path),
    ]
    try:
        process = subprocess.Popen(  # noqa: S603
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
    except FileNotFoundError as error:
        raise EncodeError(
            "ffmpeg is not installed. It is part of the worker image: render inside the "
            "worker container, or install FFmpeg on this machine."
        ) from error
    assert process.stdin is not None  # noqa: S101
    assert process.stderr is not None  # noqa: S101
    try:
        for frame in range(drawing.frame_count(index)):
            process.stdin.write(drawing.render(index, frame).tobytes())
        process.stdin.close()
    except (BrokenPipeError, OSError):
        # FFmpeg stopped reading. What it said is read below.
        pass
    except BaseException:
        process.kill()
        process.wait()
        raise
    said = process.stderr.read().decode("utf-8", errors="replace").strip()
    if process.wait() != 0:
        raise EncodeError(f"FFmpeg could not encode scene '{scene['id']}': {said[-800:]}")


def join_scenes(scenes: Sequence[SceneFile], fps: int, audio: Path, video: Path) -> None:
    """Join scene files by copying their video, and add the audio mix as AAC (RN-01)."""
    listing = video.with_name(f"{video.stem}.scenes.txt")
    partial = video.with_name(f"{video.stem}.partial.mp4")
    lines = []
    for scene in scenes:
        quoted = scene.path.resolve().as_posix().replace("'", "'\\''")
        # The exact length of each scene keeps the frames evenly spaced across the joins.
        lines.append(f"file '{quoted}'\nduration {scene.frames / fps:.6f}\n")
    listing.write_text("".join(lines), encoding="utf-8")
    try:
        _run(
            [
                FFMPEG,
                *_QUIET,
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-i",
                str(audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                AUDIO_BITRATE,
                "-movflags",
                "+faststart",
                str(partial),
            ],
            what="join the scenes",
        )
        partial.replace(video)
    finally:
        partial.unlink(missing_ok=True)
        listing.unlink(missing_ok=True)


def load_clip(path: Path) -> ClipFrames:
    """Decode a generated clip into frames for the compositor (RN-08)."""
    if not path.is_file():
        raise EncodeError(f"The clip file is missing: {path.name}")
    probed = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        what=f"read the clip {path.name}",
    )
    stream = json.loads(probed.stdout)["streams"][0]
    width, height = int(stream["width"]), int(stream["height"])
    above, _, below = str(stream["r_frame_rate"]).partition("/")
    fps = float(above) / float(below or 1)
    decoded = _run(
        [
            FFMPEG,
            *_QUIET,
            "-i",
            str(path),
            "-frames:v",
            str(_MAX_CLIP_FRAMES),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        what=f"decode the clip {path.name}",
    )
    size = width * height * 3
    frames = [
        Image.frombytes("RGB", (width, height), decoded.stdout[start : start + size])
        for start in range(0, len(decoded.stdout) - size + 1, size)
    ]
    if not frames:
        raise EncodeError(f"The clip {path.name} has no frames.")
    return ClipFrames(frames, fps=fps)


# --- the whole video ---------------------------------------------------------------------


def render_video(
    resolved: Mapping[str, Any],
    theme: Theme,
    *,
    storage_root: Path | None,
    folder: Path,
    preview: bool = False,
    workers: int = 1,
) -> RenderResult:
    """Render a resolved spec into `folder`: scene files, audio mix, video and contact sheet.

    Calling it again after a change re-encodes only the scenes that changed.
    """
    spec = for_preview(resolved) if preview else dict(resolved)
    name = "preview" if preview else "video"
    folder.mkdir(parents=True, exist_ok=True)

    scenes = render_scenes(
        spec, theme, storage_root=storage_root, folder=folder / "scenes", workers=workers
    )

    mix = mix_audio(spec, theme, storage_root=storage_root)
    audio = folder / "audio.wav"
    audio_partial = folder / "audio.partial.wav"
    try:
        write_wav(audio_partial, mix.samples, mix.sample_rate)
        audio_partial.replace(audio)
    finally:
        audio_partial.unlink(missing_ok=True)

    video = folder / f"{name}.mp4"
    join_scenes(scenes, spec["format"]["fps"], audio, video)

    sheet = folder / f"{name}_contact_sheet.jpg"
    sheet_partial = folder / f"{name}_contact_sheet.partial.jpg"
    try:
        contact_sheet(Compositor(spec, theme, storage_root=storage_root)).save(
            sheet_partial, quality=88
        )
        sheet_partial.replace(sheet)
    finally:
        sheet_partial.unlink(missing_ok=True)

    return RenderResult(
        video=video,
        audio=audio,
        contact_sheet=sheet,
        scenes=scenes,
        duration_s=mix.report.duration_s,
        preview=preview,
    )
