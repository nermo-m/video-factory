"""Resolver: authored spec plus voice timings to resolved spec (design doc sections 5 and 7.1).

The authored spec says when things happen relative to the narration ("when word 7 starts",
"0.2 seconds after the narration ends"). Once the voice has been generated the resolver
turns every such cue into an absolute time in seconds from the start of the video. The
render engine reads only the result.

This module is pure: no files, no network, no clock, no randomness. The same input always
gives the same output.

Rules (section 5.2):

* A scene lasts pad_before_s + narration + pad_after_s (defaults 0.3 and 0.4), unless
  duration_s is set. An outro adds hold_s (default 2 seconds) for its closing line.
* A word cue counts narration words from zero and fires when that word starts.
* The total may differ from target_duration_s by at most 2 seconds.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from packages.core import schemas

PAD_BEFORE_S = 0.3
PAD_AFTER_S = 0.4
OUTRO_HOLD_S = 2.0
DURATION_TOLERANCE_S = 2.0


@dataclass(frozen=True)
class WordTiming:
    """One narration word. Times are seconds from the start of the scene's audio."""

    text: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class NarrationTiming:
    """The generated voice for one scene."""

    audio_file: str
    duration_s: float
    words: list[WordTiming]


@dataclass(frozen=True)
class AssetFile:
    """Where an asset's active version is stored."""

    file: str
    licence: str | None = None
    clip_file: str | None = None


@dataclass(frozen=True)
class ResolveProblem:
    """One thing that stops the spec from being resolved: where (JSON pointer) and what."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class ResolveError(Exception):
    """The spec cannot be resolved. Carries every problem found, not only the first."""

    def __init__(self, problems: list[ResolveProblem], message: str | None = None) -> None:
        super().__init__(message or "\n".join(str(problem) for problem in problems))
        self.problems = problems


class DurationError(ResolveError):
    """The total length is more than 2 seconds away from the target."""

    def __init__(self, total_s: float, target_s: float, scenes: list[tuple[str, float]]) -> None:
        self.total_s = total_s
        self.target_s = target_s
        self.difference_s = _ms(abs(total_s - target_s))
        too_long = total_s > target_s
        # The scenes that give or take the most time come first.
        self.scenes = sorted(scenes, key=lambda item: item[1], reverse=too_long)
        listed = ", ".join(f"{scene_id} ({_text(length)} s)" for scene_id, length in self.scenes)
        message = (
            f"The video is {_text(total_s)} s long, {_text(self.difference_s)} s "
            f"{'more' if too_long else 'less'} than the {_text(target_s)} s target "
            f"({_text(DURATION_TOLERANCE_S)} s is allowed). "
            f"{'Shorten' if too_long else 'Lengthen'} these scenes, "
            f"{'longest' if too_long else 'shortest'} first: {listed}."
        )
        super().__init__([ResolveProblem("/format/target_duration_s", message)], message)


def _ms(seconds: float) -> float:
    """Round to milliseconds, so the output is stable and readable."""
    return round(seconds + 0.0, 3)


def _text(seconds: float) -> str:
    """A number of seconds for a message: 8 not 8.0, 5.7 not 5.700."""
    return f"{_ms(seconds):g}"


@dataclass
class _Scene:
    """A scene's place on the timeline while it is being resolved."""

    index: int
    source: dict[str, Any]
    start_s: float
    duration_s: float
    narration_start_s: float
    narration_duration_s: float
    timing: NarrationTiming | None
    problems: list[ResolveProblem] = field(default_factory=list)

    @property
    def path(self) -> str:
        return f"/scenes/{self.index}"

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s

    def cue_time(self, item: Mapping[str, Any], item_path: str) -> float:
        """The absolute time of an event with an optional cue. Records a problem if it has none."""
        cue = item.get("cue")
        if cue is None:
            return _ms(self.start_s)
        cue_path = f"{item_path}/cue"
        if "word" in cue:
            words = self.timing.words if self.timing is not None else []
            index = cue["word"]
            if index >= len(words):
                if self.timing is not None:
                    self.problems.append(
                        ResolveProblem(
                            cue_path,
                            f"word {index} does not exist, the narration has {len(words)} words "
                            f"(0 to {len(words) - 1})",
                        )
                    )
                return _ms(self.start_s)
            at_s = self.narration_start_s + words[index].start_s
        elif "scene_start_s" in cue:
            at_s = self.start_s + cue["scene_start_s"]
        elif "after_narration_s" in cue:
            at_s = self.narration_start_s + self.narration_duration_s + cue["after_narration_s"]
        else:
            at_s = cue["at_s"]

        at_s = _ms(at_s)
        if not _ms(self.start_s) <= at_s <= _ms(self.end_s):
            self.problems.append(
                ResolveProblem(
                    cue_path,
                    f"{_text(at_s)} s is outside this scene, which runs from "
                    f"{_text(self.start_s)} s to {_text(self.end_s)} s",
                )
            )
        return at_s


def _place(
    index: int, source: dict[str, Any], start_s: float, voice: Mapping[str, NarrationTiming]
) -> _Scene:
    """Work out a scene's length and where its narration starts."""
    problems: list[ResolveProblem] = []
    path = f"/scenes/{index}"
    narration = source["narration"]
    spoken_words = narration.split()
    timing = voice.get(source["id"]) if spoken_words else None

    if spoken_words and timing is None:
        problems.append(
            ResolveProblem(path, "there are no voice timings for this scene's narration")
        )
    elif timing is not None and len(timing.words) != len(spoken_words):
        problems.append(
            ResolveProblem(
                path,
                f"the voice timings have {len(timing.words)} words but the narration has "
                f"{len(spoken_words)}. Generate the voice for this scene again.",
            )
        )
        timing = None

    narration_duration = timing.duration_s if timing is not None else 0.0
    pad_before = source.get("pad_before_s", PAD_BEFORE_S) if spoken_words else 0.0
    pad_after = source.get("pad_after_s", PAD_AFTER_S) if spoken_words else 0.0
    hold = source.get("hold_s", OUTRO_HOLD_S) if source["kind"] == "outro" else 0.0

    if "duration_s" in source:
        duration = source["duration_s"]
        needed = pad_before + narration_duration
        if _ms(needed) > _ms(duration):
            problems.append(
                ResolveProblem(
                    f"{path}/duration_s",
                    f"the scene is set to {_text(duration)} s but its narration needs "
                    f"{_text(needed)} s ({_text(pad_before)} s before it and "
                    f"{_text(narration_duration)} s of speech)",
                )
            )
    else:
        duration = pad_before + narration_duration + pad_after + hold

    return _Scene(
        index=index,
        source=source,
        start_s=start_s,
        duration_s=duration,
        narration_start_s=start_s + pad_before,
        narration_duration_s=narration_duration,
        timing=timing,
        problems=problems,
    )


def _resolve_scene(
    scene: _Scene, asset_ids: set[str], claim_ids: set[str], first_use: dict[str, int]
) -> dict[str, Any]:
    source = scene.source
    path = scene.path

    earlier = first_use.setdefault(source["id"], scene.index)
    if earlier != scene.index:
        scene.problems.insert(
            0,
            ResolveProblem(
                f"{path}/id", f"the id '{source['id']}' is already used by scene {earlier}"
            ),
        )

    words = scene.timing.words if scene.timing is not None else []
    resolved: dict[str, Any] = {
        "id": source["id"],
        "kind": source["kind"],
        "start_s": _ms(scene.start_s),
        "duration_s": _ms(scene.duration_s),
        "narration": {
            "text": source["narration"],
            "audio_file": scene.timing.audio_file if scene.timing is not None else None,
            "start_s": _ms(scene.narration_start_s),
            "duration_s": _ms(scene.narration_duration_s),
            "words": [
                {
                    "text": word.text,
                    "start_s": _ms(scene.narration_start_s + word.start_s),
                    "end_s": _ms(scene.narration_start_s + word.end_s),
                }
                for word in words
            ],
        },
    }
    for name in ("title", "label", "sublabel"):
        if name in source:
            resolved[name] = source[name]

    if "visual" in source:
        asset_id = source["visual"]["asset_id"]
        if asset_id not in asset_ids:
            scene.problems.append(
                ResolveProblem(
                    f"{path}/visual/asset_id", f"there is no asset '{asset_id}' in this spec"
                )
            )
        resolved["visual"] = {"asset_id": asset_id, "clip": source["visual"].get("clip", False)}

    if "stat" in source:
        claim_id = source["stat"]["claim_id"]
        if claim_id not in claim_ids:
            scene.problems.append(
                ResolveProblem(
                    f"{path}/stat/claim_id", f"there is no claim '{claim_id}' in this spec"
                )
            )
        resolved["stat"] = dict(source["stat"])

    resolved["text"] = [
        {
            "content": item["content"],
            "style": item["style"],
            "at_s": scene.cue_time(item, f"{path}/text/{i}"),
        }
        for i, item in enumerate(source.get("text", []))
    ]
    if "steps" in source:
        resolved["steps"] = [
            {"text": item["text"], "at_s": scene.cue_time(item, f"{path}/steps/{i}")}
            for i, item in enumerate(source["steps"])
        ]

    overlays = []
    for i, item in enumerate(source.get("overlays", [])):
        overlay = {key: value for key, value in item.items() if key != "cue"}
        if overlay["type"] == "tag":
            overlay.setdefault("side", "left")
        overlay["at_s"] = scene.cue_time(item, f"{path}/overlays/{i}")
        overlays.append(overlay)
    resolved["overlays"] = overlays

    resolved["sound"] = [
        {
            "cue_id": item["cue_id"],
            "at_s": scene.cue_time(item, f"{path}/sound/{i}"),
            "gain_db": item.get("gain_db", 0),
        }
        for i, item in enumerate(source.get("sound", []))
    ]

    for name in ("retention_device", "transition_out"):
        if name in source:
            resolved[name] = source[name]
    if source["kind"] == "outro":
        resolved["hold_s"] = source.get("hold_s", OUTRO_HOLD_S)
    return resolved


def _resolve_assets(
    authored: Mapping[str, Any], files: Mapping[str, AssetFile]
) -> tuple[list[dict[str, Any]], list[ResolveProblem]]:
    resolved: list[dict[str, Any]] = []
    problems: list[ResolveProblem] = []
    for index, asset in enumerate(authored["assets"]):
        path = f"/assets/{index}"
        stored = files.get(asset["id"])
        if stored is None:
            problems.append(
                ResolveProblem(
                    path,
                    f"the asset '{asset['id']}' has no file yet. Generate it, upload it or "
                    "pick one from the library.",
                )
            )
            continue
        licence = stored.licence or asset.get("licence")
        if not licence:
            problems.append(
                ResolveProblem(
                    path,
                    f"the asset '{asset['id']}' has no licence recorded. Set its licence "
                    "before rendering.",
                )
            )
            continue
        entry = dict(asset)
        entry["licence"] = licence
        entry["file"] = stored.file
        if stored.clip_file is not None:
            entry["clip_file"] = stored.clip_file
        resolved.append(entry)
    return resolved, problems


def resolve(
    authored: Mapping[str, Any],
    voice: Mapping[str, NarrationTiming],
    files: Mapping[str, AssetFile],
) -> dict[str, Any]:
    """Turn an authored spec into a resolved spec.

    `voice` holds the generated narration per scene id, and `files` the stored file per
    asset id. Raises SchemaValidationError when the authored spec is not valid,
    ResolveError when something does not line up, and DurationError when the total is
    more than 2 seconds away from the target.
    """
    schemas.validate_or_raise("episode_spec", authored)

    asset_ids = {asset["id"] for asset in authored["assets"]}
    claim_ids = {claim["id"] for claim in authored["claims"]}
    first_use: dict[str, int] = {}
    problems: list[ResolveProblem] = []
    scenes: list[dict[str, Any]] = []
    lengths: list[tuple[str, float]] = []

    cursor = 0.0
    for index, source in enumerate(authored["scenes"]):
        scene = _place(index, source, cursor, voice)
        scenes.append(_resolve_scene(scene, asset_ids, claim_ids, first_use))
        problems.extend(scene.problems)
        lengths.append((source["id"], _ms(scene.duration_s)))
        cursor += scene.duration_s

    assets, asset_problems = _resolve_assets(authored, files)
    problems.extend(asset_problems)
    if problems:
        raise ResolveError(problems)

    total = _ms(cursor)
    target = authored["format"]["target_duration_s"]
    if _ms(abs(total - target)) > DURATION_TOLERANCE_S:
        raise DurationError(total, target, lengths)

    resolved = {
        "spec_version": authored["spec_version"],
        "episode_id": authored["episode_id"],
        "format": dict(authored["format"]),
        "theme": authored["theme"],
        "voice": dict(authored["voice"]),
        "seed": authored["seed"],
        "duration_s": total,
        "scenes": scenes,
        "claims": [dict(claim) for claim in authored["claims"]],
        "assets": assets,
    }
    # The output is a contract too. A failure here is a bug in this module.
    schemas.validate_or_raise("resolved_spec", resolved)
    return resolved
