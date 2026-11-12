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
