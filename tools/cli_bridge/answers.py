"""Small readers shared by the two tools: counts, and a JSON document inside an answer."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def count(value: object) -> int:
    """A token or call count from a tool's report. Anything that is not one counts as 0."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def json_object(text: str) -> dict[str, Any] | None:
    """The JSON object a model wrote, with or without a code fence or words around it."""
    candidates = [text]
    candidates += [found.group(1) for found in _FENCE.finditer(text)]
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            document = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(document, dict):
            return document
    return None
