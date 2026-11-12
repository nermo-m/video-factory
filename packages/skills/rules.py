"""Rules of the planner skills that a JSON Schema cannot express (design doc section 6).

* research: "A claim is kept only if the passage supporting it was actually retrieved"
  (FR-02). The model's word is not enough: the claim's source must be one of the pages the
  search really brought back.
* script: "Word budget is target_duration_s times 2.3 words per second at speed 1.0, minus
  pauses."
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit

from packages.adapters.llm.base import LLMResponse
from packages.core import json_patch, schemas
from packages.render.theme import check_capabilities
from packages.skills.planner import Repair

WORDS_PER_SECOND = 2.3
# The silence around each scene's narration (section 5.2: pad_before_s and pad_after_s).
PAUSE_PER_SCENE_S = 0.7
# The resolver accepts a video up to 2 seconds longer than its target (section 5.2).
TOLERANCE_S = 2.0
# The budget is an estimate: the real voice speaks a little faster or slower than 2.3
# words per second, and the resolver has the last word on the length (section 5.2). A
# script is sent back only when it is more than this far over.
SLACK = 1.05
NO_SOURCE_NOTE = "No claim is made: no source was retrieved that supports one."


def same_page(url: str) -> str:
    """An address reduced to what makes it the same page: no scheme, `www.`, fragment,
    trailing slash or difference in case of the host, and escapes written out."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = unquote(parts.path).rstrip("/")
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


def keep_sourced_claims(
    output: dict[str, Any], response: LLMResponse
) -> tuple[dict[str, Any], list[str]]:
    """FR-02: drop every claim whose source is not among the retrieved pages.

    When nothing is left the answer says so in `note`, as the schema asks. A kept claim
    gets the time of this call as `retrieved_at`: the model does not know what time it is.
    """
    claims = output.get("claims")
    if not isinstance(claims, list):
        return output, []
    retrieved = {same_page(source.url) for source in response.sources}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    kept, removed = [], []
    for claim in claims:
        url = claim.get("source_url") if isinstance(claim, dict) else None
        if isinstance(url, str) and same_page(url) in retrieved:
            kept.append({**claim, "retrieved_at": now})
        else:
            name = claim.get("id", "?") if isinstance(claim, dict) else "?"
            removed.append(f"Claim {name} was dropped: its source {url} was not retrieved.")
    cleaned = {**output, "claims": kept}
    if not kept and not str(cleaned.get("note") or "").strip():
        cleaned["note"] = NO_SOURCE_NOTE
    return cleaned, removed


def word_budget(target_duration_s: float, scenes: int, speed: float = 1.0) -> int:
    """The most words a script may have to fit its video."""
    speaking_s = target_duration_s + TOLERANCE_S - scenes * PAUSE_PER_SCENE_S
    return max(0, math.floor(speaking_s * WORDS_PER_SECOND * speed))


def count_words(text: str) -> int:
    return len(text.split())


def script_fits(
    inputs: Mapping[str, Any], output: dict[str, Any], _response: LLMResponse
) -> list[str]:
    """Problems with a script: over its word budget, or naming a claim that does not exist."""
    scenes = output["scenes"]
    words = sum(count_words(scene["narration"]) for scene in scenes)
    budget = word_budget(
        float(inputs["target_duration_s"]), len(scenes), float(inputs.get("voice_speed", 1.0))
    )
    problems = []
    if words > math.floor(budget * SLACK):
        problems.append(
            f"The script has {words} words. For {inputs['target_duration_s']} seconds in "
            f"{len(scenes)} scenes the budget is {budget} words. Cut {words - budget}."
        )
    known = {claim["id"] for claim in inputs.get("claims", {}).get("claims", [])}
    for scene in scenes:
        for claim_id in scene.get("claim_ids", []):
            if claim_id not in known:
                problems.append(
                    f"Scene {scene['id']} uses the claim {claim_id}, which research did not return."
                )
    return problems


# --- direct -----------------------------------------------------------------------------


def complete_spec(fixed: Mapping[str, Any]) -> Repair:
    """What the app knows better than the model is written into the spec as it is: the
    episode's id, its format, theme, voice and seed, and the claims research returned."""

    def repair(output: dict[str, Any], _response: LLMResponse) -> tuple[dict[str, Any], list[str]]:
        return {**output, **fixed}, []

    return repair


def spec_follows_the_plan(
    inputs: Mapping[str, Any], output: dict[str, Any], _response: LLMResponse
) -> list[str]:
    """Problems with a spec: something the theme cannot draw, narration that is not the
    script's, or a picture that is not declared."""
    problems = [str(found) for found in check_capabilities(output, inputs["capabilities"])]
    wanted = [(scene["id"], scene["narration"]) for scene in inputs["script"]["scenes"]]
    written = [(scene["id"], scene["narration"]) for scene in output["scenes"]]
    if written != wanted:
        problems.append(
            "The scenes must be the script's scenes, in its order, with the same ids and the "
            "same narration word for word. Direct them, do not rewrite them."
        )
    declared = {asset["id"]: asset for asset in output["assets"]}
    library = {entry["key"] for entry in inputs.get("library", [])}
    for scene in output["scenes"]:
        asset_id = scene.get("visual", {}).get("asset_id")
        if asset_id is not None and asset_id not in declared:
            problems.append(f"Scene {scene['id']} shows {asset_id}, which `assets` does not list.")
    for asset_id, asset in declared.items():
        if asset["origin"] == "library" and asset_id not in library:
            problems.append(
                f"The asset {asset_id} is not in the library. Its origin is not library."
            )
    return problems


# --- assets -----------------------------------------------------------------------------


def manifest_covers_the_spec(
    inputs: Mapping[str, Any], output: dict[str, Any], _response: LLMResponse
) -> list[str]:
    """Problems with an asset manifest: it must list exactly the pictures the spec shows,
    say where each is used, and write prompts in the channel's style."""
    spec, style = inputs["spec"], str(inputs.get("style_block") or "").strip()
    used: dict[str, list[str]] = {}
    clips: set[str] = set()
    for scene in spec["scenes"]:
        visual = scene.get("visual")
        if visual:
            used.setdefault(visual["asset_id"], []).append(scene["id"])
            if visual.get("clip"):
                clips.add(visual["asset_id"])
    library = {entry["key"] for entry in inputs.get("library", [])}
    listed = {entry["id"]: entry for entry in output["assets"]}
    problems = []
    for asset_id in sorted(set(used) - set(listed)):
        problems.append(f"The spec shows {asset_id}, and the manifest does not list it.")
    for asset_id in sorted(set(listed) - set(used)):
        problems.append(f"The manifest lists {asset_id}, which no scene shows.")
    for asset_id, entry in listed.items():
        if asset_id not in used:
            continue
        if sorted(entry["used_in"]) != sorted(used[asset_id]):
            problems.append(
                f"{asset_id} is used in {', '.join(used[asset_id])}. `used_in` says otherwise."
            )
        if entry["becomes_clip"] != (asset_id in clips):
            problems.append(f"`becomes_clip` of {asset_id} must match the spec's `clip`.")
        if entry["origin"] == "generated" and style and style not in entry.get("prompt", ""):
            problems.append(
                f"The prompt of {asset_id} must contain the channel style block, word for word."
            )
        if entry["origin"] == "library" and entry.get("library_key") not in library:
            problems.append(f"{asset_id} names a library asset that the library does not have.")
    return problems


# --- package ----------------------------------------------------------------------------


def package_fits_the_video(
    inputs: Mapping[str, Any], output: dict[str, Any], _response: LLMResponse
) -> list[str]:
    length = float(inputs["spec"]["format"]["target_duration_s"])
    if output["cover_frame_s"] > length:
        return [
            f"`cover_frame_s` is {output['cover_frame_s']}, "
            f"and the video is {length:g} seconds long."
        ]
    return []


# --- revise -----------------------------------------------------------------------------

MAX_PATCH_OPERATIONS = 20
# What an owner's comment may not change: these come from the episode and the channel.
PROTECTED = ("spec_version", "episode_id", "format", "theme")


def patch_leaves_a_valid_spec(
    inputs: Mapping[str, Any], output: dict[str, Any], _response: LLMResponse
) -> list[str]:
    """Problems with a revision: a patch that does not apply, or leaves a spec that is not
    valid or that the theme cannot draw."""
    patch = output["patch"]
    if len(patch) > MAX_PATCH_OPERATIONS:
        return [
            f"The patch has {len(patch)} operations. "
            f"Keep it minimal: at most {MAX_PATCH_OPERATIONS}."
        ]
    try:
        revised = json_patch.apply(inputs["spec"], patch)
    except json_patch.PatchError as error:
        return [str(error)]
    problems = [str(found) for found in schemas.validate("episode_spec", revised)]
    if problems:
        return [f"After the patch the spec is not valid. {problem}" for problem in problems]
    for name in PROTECTED:
        if revised[name] != inputs["spec"][name]:
            problems.append(f"The patch may not change `{name}`.")
    problems += [str(found) for found in check_capabilities(revised, inputs["capabilities"])]
    return problems
