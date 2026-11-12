"""Compositor: draws frame N of scene S from the resolved spec (design doc section 7.1).

The compositor reads only the resolved spec, the theme and the asset files. It has no
clock and no unseeded randomness, so the same resolved spec always gives the same frames.

Layers, back to front: sky, moon, village, drifting motes, the scene's own content (a
scroll, or slam text), hanging sprites, tags and stamps, captions, flash, smoke, shake.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from packages.render import primitives as draw
from packages.render import text
from packages.render.primitives import Box, ClipFrames, Color
from packages.render.theme import Theme

DESIGN_SIZE = (1080, 1920)
UNROLL_S = 0.6
TRANSITION_S = 0.35
SCROLL_KINDS = ("scroll", "stat", "steps")
# Text shrinks to fit its box (RN-06). This is as small as it may get before it stops.
MIN_TEXT_SIZE = 14


class RenderError(Exception):
    """A frame cannot be drawn. The message says what is missing."""


def scene_frame_counts(resolved: Mapping[str, Any]) -> list[int]:
    """How many frames each scene has.

    A scene starts and ends on the frame nearest to its start and end time. Rounding each
    scene's length on its own would add up to a video that is longer or shorter than its
    sound. This way the total is exact and no scene is more than half a frame off.
    """
    fps: int = resolved["format"]["fps"]
    counts: list[int] = []
    for scene in resolved["scenes"]:
        first = round(scene["start_s"] * fps)
        after_last = round((scene["start_s"] + scene["duration_s"]) * fps)
        counts.append(max(1, after_last - first))
    return counts


@dataclass(frozen=True)
class TextBox:
    """Where a piece of text or key art was drawn, for the safe-area check (RN-07)."""

    kind: str
    box: Box


class Compositor:
    def __init__(
        self,
        resolved: Mapping[str, Any],
        theme: Theme,
        *,
        storage_root: Path | None = None,
        clips: Mapping[str, ClipFrames] | None = None,
    ) -> None:
        self.resolved = resolved
        self.theme = theme
        self.storage_root = storage_root
        self.clips = dict(clips or {})
        self.fps: int = resolved["format"]["fps"]
        self.seed: int = resolved["seed"]
        self.size: tuple[int, int] = (resolved["format"]["width"], resolved["format"]["height"])
        self.layout: Mapping[str, Any] = theme.config["layout"]
        palette = theme.config["palette"]
        self.colors: dict[str, Color] = {
            name: draw.hex_color(value) for name, value in palette.items()
        }
        self.assets = {asset["id"]: asset for asset in resolved["assets"]}
        self.claims = {claim["id"]: claim for claim in resolved["claims"]}

    # --- public --------------------------------------------------------------------

    def frame_count(self, scene_index: int) -> int:
        """How many frames a scene has."""
        return scene_frame_counts(self.resolved)[scene_index]

    def render(
        self, scene_index: int, frame: int, *, record: list[TextBox] | None = None
    ) -> Image.Image:
        """Draw one frame of one scene as an RGB image in the spec's frame size."""
        scenes = self.resolved["scenes"]
        scene = scenes[scene_index]
        local = frame / self.fps
        at_s = scene["start_s"] + local
        boxes: list[TextBox] = record if record is not None else []

        canvas = draw.load_image(self.theme.backgrounds[0]).copy()
        self._sprites(canvas, scene, at_s, behind=True)
        for layer in self.theme.backgrounds[1:]:
            canvas.alpha_composite(draw.load_image(layer))
        draw.particles(canvas, self.seed, at_s)

        if scene["kind"] in SCROLL_KINDS:
            self._scroll(canvas, scene, at_s, local, boxes)
        impacts = self._slam(canvas, scene, at_s, boxes)
        self._sprites(canvas, scene, at_s, behind=False)
        impacts += self._tags(canvas, scene, at_s, boxes)
        impacts += self._stamps(canvas, scene, at_s, boxes)
        self._captions(canvas, scene, at_s, boxes)

        since_impact = min((at_s - impact for impact in impacts if impact <= at_s), default=None)
        if since_impact is not None:
            draw.flash(canvas, since_impact)

        duration = scene["duration_s"]
        if scene.get("transition_out") == "smoke" and local > duration - TRANSITION_S:
            draw.smoke(canvas, self.seed, (local - (duration - TRANSITION_S)) / TRANSITION_S)
        previous = scenes[scene_index - 1] if scene_index > 0 else None
        if (
            previous is not None
            and previous.get("transition_out") == "smoke"
            and local < TRANSITION_S
        ):
            draw.smoke(canvas, self.seed, 1 - local / TRANSITION_S)

        if since_impact is not None:
            offset = draw.shake_offset(since_impact)
            if offset != (0, 0):
                shaken = Image.new("RGBA", canvas.size, (*self.colors["night"], 255))
                draw.paste(shaken, canvas, *offset)
                canvas = shaken

        image = canvas.convert("RGB")
        if image.size != self.size:
            image = image.resize(self.size, Image.Resampling.LANCZOS)
        return image

    # --- fonts and assets ----------------------------------------------------------

    def _font(self, role: str, size: int, weight: int | None = None) -> Any:
        return text.load_font(self.theme.fonts[role], size, weight)

    def _fit(
        self, role: str, content: str, width: float, size: int, weight: int | None = None
    ) -> Any:
        """The largest font, from `size` down, at which the text fits the width (RN-06)."""
        return text.fit_font(
            self.theme.fonts[role],
            content,
            max_width=width,
            size=size,
            min_size=MIN_TEXT_SIZE,
            weight=weight,
        )

    def _wrapped(
        self,
        content: str,
        role: str,
        width: float,
        size: int,
        *,
        max_lines: int,
        weight: int | None = None,
        margin: int = 0,
    ) -> tuple[Any, list[str]]:
        """Wrap text onto a few lines and shrink it until every line fits the width."""
        current = size
        while True:
            font = self._font(role, current, weight)
            lines = _wrap(content, font, width, max_lines=max_lines)
            widest = max(font.getlength(line) for line in lines) + 2 * margin
            if widest <= width or current <= MIN_TEXT_SIZE:
                return font, lines
            current = max(MIN_TEXT_SIZE, int(current * 0.92))

    def _asset_image(self, asset_id: str) -> Image.Image:
        asset = self.assets.get(asset_id)
        if asset is None:
            raise RenderError(f"The spec has no asset '{asset_id}'.")
        if self.storage_root is None:
            raise RenderError("No storage folder was given, so asset files cannot be read.")
        path = self.storage_root / asset["file"]
        if not path.is_file():
            raise RenderError(f"The file for asset '{asset_id}' is missing: {asset['file']}")
        return draw.load_image(path)

    # --- scroll scenes -------------------------------------------------------------

    def _scroll(
        self,
        canvas: Image.Image,
        scene: Mapping[str, Any],
        at_s: float,
        local: float,
        boxes: list[TextBox],
    ) -> None:
        box = self.layout["scroll"]
        origin = (box["x"], box["y"])
        paper = draw.load_image(self.theme.scroll["paper"]).copy()
        if scene["kind"] == "scroll":
            self._scroll_story(paper, scene, local, origin, boxes)
        elif scene["kind"] == "stat":
            self._scroll_stat(paper, scene, origin, boxes)
        else:
            self._scroll_steps(paper, scene, at_s, origin, boxes)

        shown = draw.unrolled(paper, local / UNROLL_S)
        roller = draw.load_image(self.theme.scroll["roller"])
        roller_x = origin[0] - (roller.width - paper.width) // 2
        draw.paste(canvas, shown, *origin)
        draw.paste(canvas, roller, roller_x, origin[1] + shown.height - roller.height // 2)
        draw.paste(canvas, roller, roller_x, origin[1] - roller.height // 2)

    def _centered(
        self,
        paper: Image.Image,
        content: str,
        font: Any,
        y: int,
        color: Color,
        origin: tuple[int, int],
        boxes: list[TextBox],
        kind: str,
    ) -> int:
        """Draw a centred line on the paper. Returns the y below it."""
        layer = draw.fit_width(draw.text_layer(content, font, color), paper.width - 120)
        x = (paper.width - layer.width) // 2
        paper.alpha_composite(layer, (max(0, x), y))
        boxes.append(
            TextBox(
                kind,
                (
                    origin[0] + x,
                    origin[1] + y,
                    origin[0] + x + layer.width,
                    origin[1] + y + layer.height,
                ),
            )
        )
        return y + layer.height

    def _scroll_story(
        self,
        paper: Image.Image,
        scene: Mapping[str, Any],
        local: float,
        origin: tuple[int, int],
        boxes: list[TextBox],
    ) -> None:
        ink = self.colors["ink"]
        inner = paper.width - 120
        y = self._centered(
            paper,
            scene["title"],
            self._fit("display", scene["title"], inner, 96),
            48,
            ink,
            origin,
            boxes,
            "title",
        )
        if "label" in scene:
            y = self._centered(
                paper,
                scene["label"],
                self._fit("hand", scene["label"], inner, 58),
                y + 18,
                ink,
                origin,
                boxes,
                "label",
            )
        if "sublabel" in scene:
            faded = tuple(
                round(c * 0.55 + p * 0.45) for c, p in zip(ink, self.colors["paper"], strict=True)
            )
            font = self._fit("body", scene["sublabel"], inner, 34, 500)
            self._centered(
                paper,
                scene["sublabel"],
                font,
                y + 12,
                (faded[0], faded[1], faded[2]),
                origin,
                boxes,
                "sublabel",
            )

        visual = scene.get("visual")
        if visual is None:
            return
        left, top, width, height = 60, 300, paper.width - 120, 600
        clip = self.clips.get(visual["asset_id"]) if visual.get("clip") else None
        rng = draw.seeded(self.seed, scene["id"], "picture")
        if clip is not None:
            framed = draw.picture(
                clip.at(local), width, height, progress=0, rng=rng, ink=ink, still=False
            )
        else:
            progress = local / max(scene["duration_s"], 0.001)
            framed = draw.picture(
                self._asset_image(visual["asset_id"]),
                width,
                height,
                progress=progress,
                rng=rng,
                ink=ink,
            )
        paper.alpha_composite(framed, (left, top))
        boxes.append(
            TextBox(
                "picture",
                (
                    origin[0] + left,
                    origin[1] + top,
                    origin[0] + left + width,
                    origin[1] + top + height,
                ),
            )
        )

    def _scroll_stat(
        self,
        paper: Image.Image,
        scene: Mapping[str, Any],
        origin: tuple[int, int],
        boxes: list[TextBox],
    ) -> None:
        ink = self.colors["ink"]
        inner = paper.width - 120
        stat = scene["stat"]
        y = self._centered(
            paper,
            stat["value"],
            self._fit("display", stat["value"], inner, 280),
            230,
            ink,
            origin,
            boxes,
            "stat_value",
        )
        font, lines = self._wrapped(stat["label"], "body", inner, 54, max_lines=2, weight=600)
        for line in lines:
            y = self._centered(paper, line, font, y + 26, ink, origin, boxes, "stat_label")
        claim = self.claims.get(stat["claim_id"])
        if claim is not None:
            source = f"Source: {claim['source_name']}"
            self._centered(
                paper,
                source,
                self._fit("body", source, inner, 30, 500),
                paper.height - 130,
                ink,
                origin,
                boxes,
                "stat_source",
            )

    def _scroll_steps(
        self,
        paper: Image.Image,
        scene: Mapping[str, Any],
        at_s: float,
        origin: tuple[int, int],
        boxes: list[TextBox],
    ) -> None:
        ink = self.colors["ink"]
        inner = paper.width - 120
        if "title" in scene:
            self._centered(
                paper,
                scene["title"],
                self._fit("display", scene["title"], inner, 96),
                48,
                ink,
                origin,
                boxes,
                "title",
            )
        for index, step in enumerate(scene["steps"]):
            since = at_s - step["at_s"]
            if since < 0:
                continue
            arrive = draw.ease_out(since / 0.25)
            row = Image.new("RGBA", (inner, 150), (0, 0, 0, 0))
            row_draw = ImageDraw.Draw(row)
            row_draw.ellipse(
                (6, 31, 94, 119), fill=(*self.colors["accent"], 255), outline=(*ink, 255), width=4
            )
            number = draw.text_layer(str(index + 1), self._font("display", 60), ink)
            row.alpha_composite(number, (50 - number.width // 2, 75 - number.height // 2))
            font, lines = self._wrapped(step["text"], "hand", inner - 130, 66, max_lines=2)
            line_height = round(font.size * 1.05)
            words = Image.new("RGBA", (inner - 130, line_height * len(lines)), (0, 0, 0, 0))
            for line_index, line in enumerate(lines):
                layer = draw.fit_width(draw.text_layer(line, font, ink), inner - 130)
                words.alpha_composite(layer, (0, line_index * line_height))
            words = words.crop(words.getbbox() or (0, 0, 1, 1))
            row.alpha_composite(words, (124, max(0, 75 - words.height // 2)))
            x = 60 + round(30 * (1 - arrive))
            y = 250 + index * 190
            paper.alpha_composite(draw.with_opacity(row, arrive), (x, y))
            boxes.append(
                TextBox(
                    "step",
                    (
                        origin[0] + x,
                        origin[1] + y,
                        origin[0] + x + 124 + words.width,
                        origin[1] + y + 150,
                    ),
                )
            )

    # --- slam text -----------------------------------------------------------------

    def _slam(
        self, canvas: Image.Image, scene: Mapping[str, Any], at_s: float, boxes: list[TextBox]
    ) -> list[float]:
        items: Sequence[Mapping[str, Any]] = scene.get("text", [])
        if not items:
            return []
        area = self.layout["slam"]
        styles = self.theme.config["text_styles"]
        blocks = []
        for item in items:
            style = styles[item["style"]]
            blocks.append(
                self._wrapped(
                    item["content"],
                    style["font"],
                    area["w"],
                    style["size"],
                    max_lines=3,
                    margin=style["size"] // 16,
                )
            )
        heights = [round(font.size * 1.12) * len(lines) for font, lines in blocks]
        y = area["y"] + max(0, (area["h"] - sum(heights)) // 2)
        for item, (font, lines), height in zip(items, blocks, heights, strict=True):
            since = at_s - item["at_s"]
            if since >= 0:
                style = styles[item["style"]]
                scale = draw.slam_scale(since)
                sized = text.load_font(self.theme.fonts[style["font"]], round(font.size * scale))
                line_height = height // len(lines)
                for row, line in enumerate(lines):
                    layer = draw.text_layer(
                        line,
                        sized,
                        self.colors[style["color"]],
                        stroke=max(2, int(sized.size) // 16),
                        stroke_fill=self.colors["shadow"],
                    )
                    if scale == 1.0:
                        layer = draw.fit_width(layer, area["w"])
                    layer = draw.with_opacity(layer, since / 0.05)
                    x = area["x"] + (area["w"] - layer.width) // 2
                    top = y + row * line_height + (line_height - layer.height) // 2
                    draw.paste(canvas, layer, x, top)
                    if scale == 1.0:
                        boxes.append(TextBox("slam", (x, top, x + layer.width, top + layer.height)))
            y += height
        return [item["at_s"] for item in items]

    # --- overlays ------------------------------------------------------------------

    def _tags(
        self, canvas: Image.Image, scene: Mapping[str, Any], at_s: float, boxes: list[TextBox]
    ) -> list[float]:
        scroll = self.layout["scroll"]
        limit_right = round(DESIGN_SIZE[0] * (1 - self.layout["safe_area"]["right"]))
        limit_bottom = round(DESIGN_SIZE[1] * (1 - self.layout["safe_area"]["bottom"]))
        tags = [overlay for overlay in scene.get("overlays", []) if overlay["type"] == "tag"]
        for index, overlay in enumerate(tags):
            since = at_s - overlay["at_s"]
            if since < 0:
                continue
            rng = draw.seeded(self.seed, scene["id"], "tag", index)
            longest = max(overlay["lines"], key=len)
            font = self._fit("hand", longest, 420, 60)
            card = draw.tag(
                overlay["lines"],
                font,
                paper=(243, 230, 190),
                ink=self.colors["ink"],
                angle=float(rng.uniform(-5, 5)),
            )
            card = draw.fit_width(card, 520)
            x = 60 if overlay["side"] == "left" else limit_right - card.width
            y = min(scroll["y"] + 700 + index * 170, limit_bottom - card.height - 10)
            flight = draw.clamp01(since / 0.16)
            if flight >= 0.75:
                draw.paste(canvas, draw.with_opacity(card, (since - 0.12) / 0.08), x, y)
                boxes.append(TextBox("tag", (x, y, x + card.width, y + card.height)))
            pin = draw.load_image(self.theme.root / self.theme.config["pin"])
            pin_x, pin_y = x + card.width / 2 - pin.width / 2, y - pin.height / 3
            thrown = 1 - flight**2
            draw.paste(canvas, pin, pin_x + 240 * thrown, pin_y - 380 * thrown)
        return [overlay["at_s"] + 0.16 for overlay in tags]

    def _stamps(
        self, canvas: Image.Image, scene: Mapping[str, Any], at_s: float, boxes: list[TextBox]
    ) -> list[float]:
        scroll = self.layout["scroll"]
        stamps = [overlay for overlay in scene.get("overlays", []) if overlay["type"] == "stamp"]
        on_scroll = scene["kind"] in SCROLL_KINDS
        for index, overlay in enumerate(stamps):
            since = at_s - overlay["at_s"]
            if since < 0:
                continue
            rng = draw.seeded(self.seed, scene["id"], "stamp", index)
            color = draw.hex_color(self.theme.config["stamp_colors"][overlay.get("color", "ink")])
            font = self._fit("display", overlay["content"], 420, 88)
            mark = draw.stamp(
                overlay["content"], font, color=color, angle=-9 + float(rng.uniform(-3, 3)), rng=rng
            )
            mark = draw.fit_width(mark, 460)
            scale = 1 + 0.45 * (1 - draw.ease_out(since / 0.1))
            if scale > 1.001:
                mark = mark.resize(
                    (round(mark.width * scale), round(mark.height * scale)),
                    Image.Resampling.BILINEAR,
                )
            if on_scroll:
                center = (
                    scroll["x"] + scroll["w"] - 250,
                    scroll["y"] + scroll["h"] - 210 - index * 170,
                )
            else:
                center = (DESIGN_SIZE[0] // 2 - 40, 1300 + index * 170)
            x, y = center[0] - mark.width // 2, center[1] - mark.height // 2
            draw.paste(canvas, mark, x, y)
            if scale <= 1.001:
                boxes.append(TextBox("stamp", (x, y, x + mark.width, y + mark.height)))
        return [overlay["at_s"] for overlay in stamps]

    def _sprites(
        self, canvas: Image.Image, scene: Mapping[str, Any], at_s: float, *, behind: bool
    ) -> None:
        for overlay in scene.get("overlays", []):
            if overlay["type"] != "sprite" or (overlay["name"] == "moon") != behind:
                continue
            since = at_s - overlay["at_s"]
            if since < 0:
                continue
            sprite = draw.load_image(self.theme.sprites[overlay["name"]])
            action = overlay.get("action")
            if overlay["name"] == "moon":
                x, y, opacity = 620.0, 10.0, draw.clamp01(since / 0.6)
                if action == "rise":
                    y += 240 * (1 - draw.ease_out(since / 2.0))
                elif action == "glow":
                    opacity *= 0.82 + 0.18 * math.sin(at_s * 1.5)
                draw.paste(canvas, draw.with_opacity(sprite, opacity), x, y)
            else:
                x, y, opacity = 36.0, 0.0, draw.clamp01(since / 0.3)
                if action == "rise":
                    y += 280 * (1 - draw.ease_out(since / 1.2))
                    opacity = draw.clamp01(since / 0.5)
                turned = sprite
                if action == "sway":
                    turned = draw.rotated_about_top(sprite, 4 * math.sin(2 * math.pi * 0.3 * at_s))
                    x -= (turned.width - sprite.width) / 2
                    y -= turned.height / 2
                draw.paste(canvas, draw.with_opacity(turned, opacity), x, y)

    # --- captions ------------------------------------------------------------------

    def _captions(
        self, canvas: Image.Image, scene: Mapping[str, Any], at_s: float, boxes: list[TextBox]
    ) -> None:
        words = scene["narration"]["words"]
        active = text.active_caption(text.group_captions(words), words, at_s)
        if active is None:
            return
        group, highlighted = active
        spoken = [words[index]["text"] for index in group]
        area = self.layout["captions"]
        font = self._fit("body", " ".join(spoken), area["w"] - 48, 84, 800)
        row = draw.caption_row(
            spoken,
            group.index(highlighted),
            font,
            color=self.colors["text"],
            highlight=self.colors["accent"],
            outline=self.colors["shadow"],
        )
        row = draw.fit_width(row, area["w"])
        x = area["x"] + (area["w"] - row.width) // 2
        y = area["y"] + (area["h"] - row.height) // 2
        draw.paste(canvas, row, x, y)
        boxes.append(TextBox("caption", (x, y, x + row.width, y + row.height)))


def _wrap(content: str, font: Any, width: float, *, max_lines: int) -> list[str]:
    """Break a label into at most `max_lines` lines that fit the width."""
    lines: list[str] = []
    current = ""
    for word in content.split():
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > width and len(lines) < max_lines - 1:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
