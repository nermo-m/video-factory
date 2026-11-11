"""Themes: what a look is made of, and what it can draw.

A theme is a folder with `theme.json` (palette, fonts, layout, asset files) and
`capabilities.json` (scene kinds, text styles, overlay types, sprites, sound cues and
transitions). The capabilities are given to the planner and checked here, so a spec cannot
ask for something the renderer cannot draw (design doc section 6).

v1 has one theme, night_scrolls (decision D10).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

THEMES_DIR = Path(__file__).resolve().parent
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@dataclass(frozen=True)
class Theme:
    """A loaded theme. Every path is absolute and inside the theme's own folder."""

    name: str
    root: Path
    capabilities: dict[str, Any]
    config: dict[str, Any]
    fonts: dict[str, Path]
    backgrounds: list[Path]
    scroll: dict[str, Path]
    sprites: dict[str, Path]
    sounds: dict[str, Path]


def _read(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def load_theme(name: str) -> Theme:
    """Load a theme by name. Raises KeyError when there is no such theme."""
    root = THEMES_DIR / name
    if not _NAME.fullmatch(name) or not (root / "capabilities.json").is_file():
        raise KeyError(f"There is no theme named '{name}'.")

    config = _read(root / "theme.json")

    def paths(section: str) -> dict[str, Path]:
        return {key: root / value for key, value in config[section].items()}

    return Theme(
        name=name,
        root=root,
        capabilities=_read(root / "capabilities.json"),
        config=config,
        fonts=paths("fonts"),
        backgrounds=[root / value for value in config["backgrounds"]],
        scroll=paths("scroll"),
        sprites=paths("sprites"),
        sounds=paths("sounds"),
    )


@dataclass(frozen=True)
class CapabilityProblem:
    """Something a spec asks for that the theme cannot draw: where and what."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _missing(path: str, what: str, value: str, known: list[str]) -> CapabilityProblem:
    return CapabilityProblem(path, f"the theme has no {what} '{value}'. It has: {', '.join(known)}")


def check_capabilities(
    authored: Mapping[str, Any], capabilities: Mapping[str, Any]
) -> list[CapabilityProblem]:
    """Everything in an authored spec that this theme cannot draw. Empty means it all fits.

    The spec is expected to be valid against the episode spec schema already.
    """
    if authored["theme"] != capabilities["theme"]:
        return [
            CapabilityProblem(
                "/theme",
                f"this is the theme '{capabilities['theme']}', "
                f"the spec asks for '{authored['theme']}'",
            )
        ]

    problems: list[CapabilityProblem] = []
    sprites: dict[str, list[str]] = capabilities["sprites"]
    for index, scene in enumerate(authored["scenes"]):
        path = f"/scenes/{index}"
        if scene["kind"] not in capabilities["scene_kinds"]:
            problems.append(
                _missing(f"{path}/kind", "scene kind", scene["kind"], capabilities["scene_kinds"])
            )
        for i, item in enumerate(scene.get("text", [])):
            if item["style"] not in capabilities["text_styles"]:
                problems.append(
                    _missing(
                        f"{path}/text/{i}/style",
                        "text style",
                        item["style"],
                        capabilities["text_styles"],
                    )
                )
        for i, overlay in enumerate(scene.get("overlays", [])):
            overlay_path = f"{path}/overlays/{i}"
            kind = overlay["type"]
            if kind not in capabilities["overlay_types"]:
                problems.append(
                    _missing(
                        f"{overlay_path}/type", "overlay type", kind, capabilities["overlay_types"]
                    )
                )
            elif (
                kind == "stamp" and overlay.get("color", "ink") not in capabilities["stamp_colors"]
            ):
                problems.append(
                    _missing(
                        f"{overlay_path}/color",
                        "stamp colour",
                        overlay["color"],
                        capabilities["stamp_colors"],
                    )
                )
            elif kind == "sprite":
                name = overlay["name"]
                if name not in sprites:
                    problems.append(_missing(f"{overlay_path}/name", "sprite", name, list(sprites)))
                elif "action" in overlay and overlay["action"] not in sprites[name]:
                    problems.append(
                        CapabilityProblem(
                            f"{overlay_path}/action",
                            f"the sprite '{name}' cannot '{overlay['action']}'. "
                            f"It can: {', '.join(sprites[name])}",
                        )
                    )
        for i, cue in enumerate(scene.get("sound", [])):
            if cue["cue_id"] not in capabilities["sound_cues"]:
                problems.append(
                    _missing(
                        f"{path}/sound/{i}/cue_id",
                        "sound cue",
                        cue["cue_id"],
                        capabilities["sound_cues"],
                    )
                )
        transition = scene.get("transition_out")
        if transition is not None and transition not in capabilities["transitions"]:
            problems.append(
                _missing(
                    f"{path}/transition_out", "transition", transition, capabilities["transitions"]
                )
            )
    return problems
