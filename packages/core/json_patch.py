"""A small JSON Patch (RFC 6902): add, remove and replace.

The revise skill answers with a patch to the episode spec, and the owner sees it as a
diff before it is applied (design doc section 6). Three operations are enough for that,
so this project carries no patch library. `apply` never changes the document it is given.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

OPERATIONS = ("add", "remove", "replace")


class PatchError(ValueError):
    """A patch that cannot be applied. The message names the operation and the reason."""


def _parts(pointer: str) -> list[str]:
    """A JSON Pointer (RFC 6901) as its parts. `""` is the whole document."""
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise PatchError(f"The path '{pointer}' must start with '/'.")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _index(part: str, length: int, *, may_append: bool) -> int:
    if part == "-" and may_append:
        return length
    if not part.isdecimal() or (len(part) > 1 and part.startswith("0")):
        raise PatchError(f"'{part}' is not a position in a list.")
    position = int(part)
    if position > length or (position == length and not may_append):
        raise PatchError(f"The list has no position {position}.")
    return position


def _parent(document: Any, parts: list[str], path: str) -> Any:
    node = document
    for part in parts[:-1]:
        if isinstance(node, dict):
            if part not in node:
                raise PatchError(f"Nothing exists at '{path}'.")
            node = node[part]
        elif isinstance(node, list):
            node = node[_index(part, len(node), may_append=False)]
        else:
            raise PatchError(f"Nothing exists at '{path}'.")
    return node


def apply(document: Any, patch: Sequence[Mapping[str, Any]]) -> Any:
    """The document with the patch applied, as a new document."""
    result = copy.deepcopy(document)
    for number, operation in enumerate(patch, start=1):
        name, path = operation.get("op"), operation.get("path")
        if name not in OPERATIONS or not isinstance(path, str):
            raise PatchError(
                f"Operation {number} must be one of {', '.join(OPERATIONS)} on a path."
            )
        if name != "remove" and "value" not in operation:
            raise PatchError(f"Operation {number} ({name} {path}) has no value.")
        try:
            parts = _parts(path)
            if not parts:
                raise PatchError("it would replace the whole document.")
            parent, last = _parent(result, parts, path), parts[-1]
            value = copy.deepcopy(operation.get("value"))
            if isinstance(parent, dict):
                if name != "add" and last not in parent:
                    raise PatchError(f"Nothing exists at '{path}'.")
                if name == "remove":
                    del parent[last]
                else:
                    parent[last] = value
            elif isinstance(parent, list):
                position = _index(last, len(parent), may_append=name == "add")
                if name == "add":
                    parent.insert(position, value)
                elif name == "remove":
                    del parent[position]
                else:
                    parent[position] = value
            else:
                raise PatchError(f"Nothing exists at '{path}'.")
        except PatchError as error:
            raise PatchError(f"Operation {number} ({name} {path}): {error}") from None
    return result
