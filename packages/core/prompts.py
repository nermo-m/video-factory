"""The prompt a picture is made from (Director mode).

In a 2.1 plan the look of the pictures is written once, as `style`, and every character is
described once. A picture's own prompt says what is in that scene and lists who is in it.
The prompt that is sent to the image model is put together here, when the picture is
made: the style, then each character in the picture, then the scene.

So a character looks the same in every scene, and editing one description reaches every
picture that shows the character. A 2.0 plan has neither, and its prompt is sent as it is.

This module is pure.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SEPARATOR = "\n\n"


def compose(spec: Mapping[str, Any], asset: Mapping[str, Any]) -> str | None:
    """The whole prompt of one picture of a plan, or None when the picture has no prompt
    (an uploaded or a library picture)."""
    prompt = asset.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    if spec.get("spec_version") == "2.0":
        return prompt
    described = {character["id"]: character for character in spec.get("characters", [])}
    parts = [str(spec["style"]).strip()] if str(spec.get("style") or "").strip() else []
    for character_id in asset.get("characters", []):
        character = described.get(character_id)
        if character is not None:
            parts.append(f"{character['name']}: {character['description']}".strip())
    parts.append(prompt.strip())
    return SEPARATOR.join(parts)
