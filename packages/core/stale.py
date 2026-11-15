"""Which scenes an edit of the spec makes stale (design doc section 4.2).

"Editing the spec after plan approval marks only the affected scenes stale. Affected
means: narration changed marks voice and render stale for that scene, visual or asset
changed marks render stale for that scene, timing changed marks render stale for that
scene and every later scene."

What the three words cover here:

* narration: the scene's narration text, or the episode's voice settings (every scene);
* timing: the scene's pads, fixed duration and hold, a scene added, removed or moved;
* visual or asset: everything else a scene shows or plays (texts, overlays, sound cues,
  cue times, its picture and that picture's asset entry), a transition (the scene it
  leaves and the scene it enters), and the episode's seed, theme and format (every scene).

A field that is never drawn or spoken, such as `retention_device`, makes nothing stale.

This module is pure: it compares two authored specs and nothing else.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from packages.core import prompts

_TIMING_FIELDS = ("pad_before_s", "pad_after_s", "duration_s", "hold_s")
# Not part of the picture or the sound. `id` is how scenes are matched.
_NOT_RENDERED = (
    "id",
    "narration",
    "narration_from",
    "retention_device",
    "transition_out",
    *_TIMING_FIELDS,
)
# `captions` and `music` are the switches of a plan of shots. A plan without them has both.
_EVERY_SCENE_DRAWN_AGAIN = ("seed", "theme", "format", "captions", "music")


@dataclass(frozen=True)
class StaleScenes:
    """Scene ids whose voice and whose render are out of date, in scene order."""

    voice: tuple[str, ...] = ()
    render: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.voice or self.render)

    def merged(self, other: StaleScenes, *, order: Sequence[str]) -> StaleScenes:
        """Both sets together, in the given scene order. Ids not in `order` are dropped."""
        return StaleScenes(
            voice=_ordered({*self.voice, *other.voice}, order),
            render=_ordered({*self.render, *other.render}, order),
        )

    def to_json(self) -> dict[str, list[str]]:
        return {"voice": list(self.voice), "render": list(self.render)}

    @classmethod
    def from_json(cls, stored: Mapping[str, Any]) -> StaleScenes:
        return cls(voice=tuple(stored.get("voice", ())), render=tuple(stored.get("render", ())))


def _ordered(ids: Iterable[str], order: Sequence[str]) -> tuple[str, ...]:
    wanted = set(ids)
    return tuple(scene_id for scene_id in order if scene_id in wanted)


def _shown(
    scene: Mapping[str, Any], assets: Mapping[str, Any], spec: Mapping[str, Any]
) -> dict[str, Any]:
    """Everything a scene shows or plays, with the asset entry of its picture.

    In a plan of shots a picture is made from more than its own entry: the style and the
    description of each character in it are written once for the whole plan. So the
    picture counts as changed when the prompt it would be made from has changed, and a
    character that is only given another id changes nothing.
    """
    shown = {key: value for key, value in scene.items() if key not in _NOT_RENDERED}
    if "visual" in scene:
        asset = assets.get(scene["visual"]["asset_id"])
        if asset is not None and spec.get("spec_version") != "2.0":
            asset = {
                **{key: value for key, value in asset.items() if key != "characters"},
                "made_from": prompts.compose(spec, asset),
            }
        shown["asset"] = asset
    return shown


def affected_scenes(old: Mapping[str, Any], new: Mapping[str, Any]) -> StaleScenes:
    """The scenes of the new spec whose voice or render the edit has made stale."""
    order = [scene["id"] for scene in new["scenes"]]
    spoken = [scene["id"] for scene in new["scenes"] if scene["narration"].strip()]
    voice: set[str] = set()
    render: set[str] = set()

    if old["voice"] != new["voice"]:
        voice.update(spoken)
        render.update(order)
    if any(old.get(field, True) != new.get(field, True) for field in _EVERY_SCENE_DRAWN_AGAIN):
        render.update(order)

    before = {scene["id"]: scene for scene in old["scenes"]}
    old_order = [scene["id"] for scene in old["scenes"]]
    old_assets = {asset["id"]: asset for asset in old["assets"]}
    new_assets = {asset["id"]: asset for asset in new["assets"]}

    for index, scene in enumerate(new["scenes"]):
        scene_id = scene["id"]
        earlier = before.get(scene_id)
        moved = index >= len(old_order) or old_order[index] != scene_id
        if earlier is None:
            if scene["narration"].strip():
                voice.add(scene_id)
            render.update(order[index:])
            continue
        if earlier["narration"] != scene["narration"]:
            voice.add(scene_id)
            render.add(scene_id)
        if moved or any(earlier.get(field) != scene.get(field) for field in _TIMING_FIELDS):
            render.update(order[index:])
        if _shown(earlier, old_assets, old) != _shown(scene, new_assets, new):
            render.add(scene_id)
        if earlier.get("transition_out") != scene.get("transition_out"):
            render.update(order[index : index + 2])

    # A scene removed from the end moves nothing, but the video must be joined again.
    # That is the render state's business: its join job always runs.
    return StaleScenes(voice=_ordered(voice, order), render=_ordered(render, order))
