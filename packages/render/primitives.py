"""Drawing primitives for the render engine (design doc section 7.1).

Every function here is pure: it draws on the image it is given, from its arguments and a
time, with no clock and no unseeded randomness. The same call always draws the same
pixels, which is what lets a resolved spec render the same frames twice.

Coordinates are in the theme's design space, 1080 by 1920.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Color = tuple[int, int, int]
Box = tuple[int, int, int, int]


# --- small helpers -------------------------------------------------------------------


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def ease_out(value: float) -> float:
    """Fast start, gentle stop."""
    return 1 - (1 - clamp01(value)) ** 3


def ease_out_back(value: float) -> float:
    """Like ease_out, but overshoots a little before it settles."""
    x = clamp01(value) - 1
    return 1 + 2.4 * x**3 + 1.4 * x**2


def hex_color(value: str) -> Color:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def seeded(seed: int, *keys: str | int) -> np.random.Generator:
    """A random source that depends only on the spec seed and the given keys."""
    parts = [seed] + [zlib.crc32(str(key).encode("utf-8")) for key in keys]
    return np.random.default_rng(parts)


@lru_cache(maxsize=64)
def load_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def paste(canvas: Image.Image, layer: Image.Image, x: float, y: float) -> None:
    """Alpha-composite a layer onto the canvas at any position, cropping what falls outside."""
    left, top = round(x), round(y)
    source_left, source_top = max(0, -left), max(0, -top)
    right = min(canvas.width, left + layer.width)
    bottom = min(canvas.height, top + layer.height)
    if right <= max(left, 0) or bottom <= max(top, 0):
        return
    region = layer.crop(
        (
            source_left,
            source_top,
            source_left + right - max(left, 0),
            source_top + bottom - max(top, 0),
        )
    )
    canvas.alpha_composite(region, (max(left, 0), max(top, 0)))


def fit_width(layer: Image.Image, max_width: int) -> Image.Image:
    """Scale a layer down when it is wider than allowed. The last guard of the safe area:
    whatever the text, nothing is ever drawn wider than its box (RN-07)."""
    if layer.width <= max_width:
        return layer
    height = max(1, round(layer.height * max_width / layer.width))
    return layer.resize((max_width, height), Image.Resampling.LANCZOS)


def with_opacity(layer: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 1:
        return layer
    faded = layer.copy()
    faded.putalpha(faded.getchannel("A").point(lambda value: round(value * clamp01(opacity))))
    return faded


def text_layer(
    content: str,
    font: ImageFont.FreeTypeFont,
    fill: Color,
    *,
    stroke: int = 0,
    stroke_fill: Color = (0, 0, 0),
) -> Image.Image:
    """The text on a transparent layer that is exactly as large as it needs to be."""
    box = font.getbbox(content, stroke_width=stroke)
    left, top = math.floor(box[0]), math.floor(box[1])
    right, bottom = math.ceil(box[2]), math.ceil(box[3])
    layer = Image.new("RGBA", (max(1, right - left), max(1, bottom - top)), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        (-left, -top),
        content,
        font=font,
        fill=(*fill, 255),
        stroke_width=stroke,
        stroke_fill=(*stroke_fill, 255),
    )
    return layer


def cover(
    image: Image.Image,
    width: int,
    height: int,
    zoom: float = 1.0,
    pan: tuple[float, float] = (0.5, 0.5),
) -> Image.Image:
    """Scale and crop an image to fill width by height (RN-08).

    `zoom` 1.0 just covers the area. `pan` chooses which part shows when there is spare
    image: (0, 0) is the top left, (1, 1) the bottom right.
    """
    scale = max(width / image.width, height / image.height) * max(1.0, zoom)
    scaled = image.resize(
        (max(width, round(image.width * scale)), max(height, round(image.height * scale))),
        Image.Resampling.BILINEAR,
    )
    left = round((scaled.width - width) * clamp01(pan[0]))
    top = round((scaled.height - height) * clamp01(pan[1]))
    return scaled.crop((left, top, left + width, top + height))


# --- clips ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClipFrames:
    """The decoded frames of a generated clip.

    A clip is about five seconds long and a scene may be longer. `mode` says what happens
    after the last frame: "freeze" holds it, "loop" starts again (RN-08).
    """

    frames: Sequence[Image.Image]
    fps: float
    mode: str = "freeze"

    def at(self, seconds: float) -> Image.Image:
        index = max(0, int(seconds * self.fps))
        if index >= len(self.frames):
            index = index % len(self.frames) if self.mode == "loop" else len(self.frames) - 1
        return self.frames[index]


# --- ambience and effects ------------------------------------------------------------


def particles(canvas: Image.Image, seed: int, at_s: float, count: int = 34) -> None:
    """Slow motes of light drifting over the scene. Their paths depend only on the seed."""
    rng = seeded(seed, "particles")
    base = rng.uniform(0, 1, (count, 2))
    drift = rng.uniform(-14, 14, count)
    rise = rng.uniform(6, 22, count)
    phase = rng.uniform(0, 2 * math.pi, count)
    size = rng.uniform(1.6, 3.6, count)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for i in range(count):
        x = (
            base[i, 0] * canvas.width + drift[i] * at_s + 18 * math.sin(at_s * 0.6 + phase[i])
        ) % canvas.width
        y = (base[i, 1] * canvas.height * 0.8 - rise[i] * at_s) % (canvas.height * 0.8)
        glow = 0.5 + 0.5 * math.sin(at_s * 1.7 + phase[i])
        alpha = round(60 + 110 * glow)
        draw.ellipse(
            (x - size[i], y - size[i], x + size[i], y + size[i]), fill=(255, 226, 170, alpha)
        )
    canvas.alpha_composite(layer)


def flash(
    canvas: Image.Image, since_s: float, length_s: float = 0.12, strength: float = 0.35
) -> None:
    """A brief white flash that fades out, used when text slams in."""
    if not 0 <= since_s < length_s:
        return
    alpha = round(255 * strength * (1 - since_s / length_s))
    canvas.alpha_composite(Image.new("RGBA", canvas.size, (255, 255, 255, alpha)))


def shake_offset(since_s: float, length_s: float = 0.3, amount: float = 14.0) -> tuple[int, int]:
    """How far the frame is knocked off centre this long after an impact."""
    if not 0 <= since_s < length_s:
        return (0, 0)
    fade = 1 - since_s / length_s
    return (
        round(amount * fade * math.sin(since_s * 95)),
        round(amount * fade * math.cos(since_s * 71)),
    )


@lru_cache(maxsize=8)
def _smoke_field(seed: int, width: int, height: int) -> np.ndarray:
    rng = seeded(seed, "smoke")
    coarse = (rng.uniform(0, 1, (20, 12)) * 255).astype(np.uint8)
    field = Image.fromarray(coarse, "L").resize((width, height), Image.Resampling.BICUBIC)
    return np.asarray(field, dtype=np.float32) / 255.0


def smoke(canvas: Image.Image, seed: int, progress: float) -> None:
    """Smoke that covers the frame as progress goes from 0 to 1 (RN-03).

    It is drawn inside the scene itself: the outgoing scene runs it forwards, the incoming
    scene backwards, so scene files can be joined without a cross-file fade.
    """
    progress = clamp01(progress)
    if progress <= 0:
        return
    field = _smoke_field(seed, canvas.width // 4, canvas.height // 4)
    coverage = np.clip((progress - field * 0.7) / 0.3, 0, 1)
    alpha = Image.fromarray((coverage * 255).astype(np.uint8), "L").resize(
        canvas.size, Image.Resampling.BILINEAR
    )
    cloud = Image.new("RGBA", canvas.size, (24, 26, 44, 255))
    cloud.putalpha(alpha)
    canvas.alpha_composite(cloud)


# --- text ----------------------------------------------------------------------------


def slam_scale(since_s: float, length_s: float = 0.14) -> float:
    """Slam text starts oversized and snaps to its size."""
    if since_s >= length_s:
        return 1.0
    return 1.0 + 0.5 * (1 - ease_out(since_s / length_s))


def caption_row(
    words: Sequence[str],
    highlighted: int,
    font: ImageFont.FreeTypeFont,
    *,
    color: Color,
    highlight: Color,
    outline: Color,
) -> Image.Image:
    """One caption group on a transparent layer, with one word highlighted (RN-06)."""
    stroke = max(4, int(font.size) // 12)
    space = font.getlength(" ")
    pieces = [
        text_layer(
            word, font, highlight if i == highlighted else color, stroke=stroke, stroke_fill=outline
        )
        for i, word in enumerate(words)
    ]
    ascent, descent = font.getmetrics()
    height = ascent + descent + stroke * 2
    width = round(sum(piece.width for piece in pieces) + space * (len(pieces) - 1))
    row = Image.new("RGBA", (max(1, width), height), (0, 0, 0, 0))
    x = 0.0
    for word, piece in zip(words, pieces, strict=True):
        top = math.floor(font.getbbox(word, stroke_width=stroke)[1])
        row.alpha_composite(piece, (round(x), max(0, top + stroke)))
        x += piece.width + space
    return row


# --- paper things --------------------------------------------------------------------


def tag(
    lines: Sequence[str],
    font: ImageFont.FreeTypeFont,
    *,
    paper: Color,
    ink: Color,
    angle: float,
) -> Image.Image:
    """A paper tag with handwritten lines, slightly turned."""
    rows = [text_layer(line, font, ink) for line in lines]
    line_height = round(font.size * 1.05)
    width = max(row.width for row in rows) + 64
    height = line_height * len(rows) + 58
    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=10, fill=(*paper, 255), outline=(*ink, 255), width=3
    )
    for i, row in enumerate(rows):
        card.alpha_composite(
            row, ((width - row.width) // 2, 34 + i * line_height + (line_height - row.height) // 2)
        )
    return card.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


def stamp(
    content: str,
    font: ImageFont.FreeTypeFont,
    *,
    color: Color,
    angle: float,
    rng: np.random.Generator,
) -> Image.Image:
    """An ink stamp: boxed capitals, a little uneven, as if pressed by hand."""
    label = text_layer(content, font, color)
    width, height = label.width + 72, label.height + 60
    mark = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(mark)
    draw.rounded_rectangle((4, 4, width - 5, height - 5), radius=14, outline=(*color, 255), width=9)
    mark.alpha_composite(label, ((width - label.width) // 2, (height - label.height) // 2))

    # Ink never lands evenly: thin it out in soft patches.
    coarse = (rng.uniform(0.62, 1.0, (max(2, height // 18), max(2, width // 18))) * 255).astype(
        np.uint8
    )
    wear = Image.fromarray(coarse, "L").resize((width, height), Image.Resampling.BICUBIC)
    alpha = (
        np.asarray(mark.getchannel("A"), dtype=np.float32)
        * np.asarray(wear, dtype=np.float32)
        / 255
    )
    mark.putalpha(Image.fromarray((alpha * 0.9).astype(np.uint8), "L"))
    return mark.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


def unrolled(paper: Image.Image, progress: float) -> Image.Image:
    """The part of a scroll that has unrolled so far, from the top down."""
    visible = max(1, round(paper.height * ease_out(progress)))
    return paper.crop((0, 0, paper.width, visible))


def picture(
    image: Image.Image,
    width: int,
    height: int,
    *,
    progress: float,
    rng: np.random.Generator,
    ink: Color,
    still: bool = True,
) -> Image.Image:
    """A framed picture. A still image slowly zooms and drifts, a clip frame is shown as is."""
    if still:
        direction = (float(rng.uniform(0.2, 0.8)), float(rng.uniform(0.2, 0.8)))
        zoom = 1.04 + 0.08 * clamp01(progress)
        pan = (0.5 + (direction[0] - 0.5) * progress, 0.5 + (direction[1] - 0.5) * progress)
        filled = cover(image, width, height, zoom, pan)
    else:
        filled = cover(image, width, height)
    framed = filled.convert("RGBA")
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=12, fill=255)
    framed.putalpha(mask)
    ImageDraw.Draw(framed).rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=12, outline=(*ink, 255), width=5
    )
    return framed


def rotated_about_top(sprite: Image.Image, angle: float) -> Image.Image:
    """Turn a hanging sprite around the middle of its top edge, like a lantern on a string."""
    size = max(sprite.width, sprite.height) * 2
    stage = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    stage.alpha_composite(sprite, ((size - sprite.width) // 2, size // 2))
    return stage.rotate(angle, resample=Image.Resampling.BICUBIC, center=(size / 2, size / 2))
