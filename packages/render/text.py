"""Caption grouping and font fitting for the render engine (RN-06, RN-10).

Captions are shown word by word, in small groups, with the word being spoken
highlighted. Fonts are loaded by path from the theme, never from the system.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import ImageFont

MAX_GROUP_WORDS = 3
MAX_GROUP_CHARS = 14
# A caption stays on screen for a moment after its last word, so it can be read.
CAPTION_LINGER_S = 0.35
_SENTENCE_END = (".", "!", "?")


def group_captions(words: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    """Split narration words into caption groups, as lists of word indexes.

    A group has at most 3 words and at most 14 characters including spaces. A longer
    single word stands alone. A group also ends where its sentence ends.
    """
    groups: list[list[int]] = []
    current: list[int] = []
    length = 0
    for index, word in enumerate(words):
        spoken = str(word["text"])
        added = len(spoken) + (1 if current else 0)
        if current and (len(current) >= MAX_GROUP_WORDS or length + added > MAX_GROUP_CHARS):
            groups.append(current)
            current, length, added = [], 0, len(spoken)
        current.append(index)
        length += added
        if spoken.endswith(_SENTENCE_END):
            groups.append(current)
            current, length = [], 0
    if current:
        groups.append(current)
    return groups


def active_caption(
    groups: Sequence[Sequence[int]], words: Sequence[Mapping[str, Any]], at_s: float
) -> tuple[list[int], int] | None:
    """The caption group on screen at this time and the index of its highlighted word.

    Times are absolute, as in the resolved spec. Returns None between captions.
    """
    for position, group in enumerate(groups):
        start = float(words[group[0]]["start_s"])
        last_end = float(words[group[-1]]["end_s"])
        is_last = position == len(groups) - 1
        next_start = float(words[groups[position + 1][0]]["start_s"]) if not is_last else None
        end = last_end + CAPTION_LINGER_S
        if next_start is not None:
            end = min(end, next_start)
        if start <= at_s < end:
            spoken = [index for index in group if float(words[index]["start_s"]) <= at_s]
            return list(group), spoken[-1]
    return None


@lru_cache(maxsize=256)
def load_font(path: Path, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    """Load a bundled font by path. `weight` selects a weight of a variable font."""
    # The basic layout engine is asked for by name. Left to itself Pillow uses Raqm
    # whenever the FriBiDi library happens to be installed, and the same text then lands
    # on slightly different pixels from one machine or image to the next.
    font = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)
    if weight is not None:
        axes = font.get_variation_axes()
        values = [
            float(weight) if _is_weight_axis(axis) else float(axis["default"] or 0) for axis in axes
        ]
        font.set_variation_by_axes(values)
    return font


def _is_weight_axis(axis: Mapping[str, Any]) -> bool:
    name = axis.get("name")
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    return str(name).lower() == "weight"


def fit_font(
    path: Path,
    content: str,
    *,
    max_width: float,
    size: int,
    min_size: int,
    weight: int | None = None,
) -> ImageFont.FreeTypeFont:
    """The largest font from `size` down to `min_size` at which the text fits the width."""
    current = size
    while current > min_size:
        font = load_font(path, current, weight)
        if font.getlength(content) <= max_width:
            return font
        current = max(min_size, int(current * 0.94))
    return load_font(path, min_size, weight)
