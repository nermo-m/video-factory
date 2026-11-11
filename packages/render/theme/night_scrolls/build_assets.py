"""Draw the night_scrolls artwork and synthesise its sound cues.

    uv run python -m packages.render.theme.night_scrolls.build_assets

Every image and sound of the theme is made by this script, from code and a fixed random
seed. Nothing is traced, sampled or copied from anywhere, which is what makes the assets
original (design doc section 13, rule 2). The results are committed, so the render engine
never needs to run this. Run it again only to change the artwork, then review the images.

Fonts are the one exception: they are third-party OFL fonts in assets/fonts.
"""

from __future__ import annotations

import math
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent / "assets"
WIDTH, HEIGHT = 1080, 1920
SEED = 20261111
SAMPLE_RATE = 44100

Color = tuple[int, int, int]


def _rng(offset: int) -> np.random.Generator:
    return np.random.default_rng(SEED + offset)


def _gradient(stops: list[tuple[float, Color]], height: int, width: int) -> Image.Image:
    """A vertical gradient through colour stops given as (position 0..1, colour)."""
    positions = np.array([stop[0] for stop in stops])
    y = np.linspace(0.0, 1.0, height)
    channels = [np.interp(y, positions, [stop[1][c] for stop in stops]) for c in range(3)]
    column = np.stack(channels, axis=1).astype(np.uint8)
    return Image.fromarray(np.repeat(column[:, None, :], width, axis=1), "RGB")


# --- backgrounds ---------------------------------------------------------------------


def sky() -> Image.Image:
    """Night sky: deep blue falling to a violet horizon, with stars."""
    rng = _rng(1)
    image = _gradient(
        [(0.0, (6, 10, 26)), (0.5, (14, 24, 58)), (0.72, (38, 38, 84)), (1.0, (56, 46, 92))],
        HEIGHT,
        WIDTH,
    )
    stars = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(stars)
    for _ in range(520):
        x = int(rng.integers(0, WIDTH))
        # More stars high up, none near the horizon glow.
        y = int(abs(rng.normal(0, 0.33)) * HEIGHT * 0.75) % int(HEIGHT * 0.68)
        radius = float(rng.choice([0.7, 0.9, 1.2, 1.7], p=[0.5, 0.3, 0.15, 0.05]))
        brightness = int(rng.integers(90, 255))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=brightness)
    stars = stars.filter(ImageFilter.GaussianBlur(0.7))
    glow = Image.new("RGB", (WIDTH, HEIGHT), (228, 232, 255))
    return Image.composite(glow, image, stars)


def _ridge(rng: np.random.Generator, base: float, swing: float) -> np.ndarray:
    """Height of a hill line across the frame, as y pixels."""
    x = np.linspace(0, 1, WIDTH)
    line = np.zeros(WIDTH)
    for octave in range(1, 5):
        phase = rng.uniform(0, 2 * math.pi)
        line += np.sin(x * octave * 2.1 * math.pi + phase) / octave
    return base + line / 2.1 * swing


def _fill_below(
    draw: ImageDraw.ImageDraw, ridge: np.ndarray, color: tuple[int, int, int, int]
) -> None:
    points = [(float(x), float(y)) for x, y in enumerate(ridge)]
    draw.polygon([*points, (WIDTH, HEIGHT), (0, HEIGHT)], fill=color)


def _house(
    draw: ImageDraw.ImageDraw, x: float, ground: float, width: float, height: float
) -> list[tuple[float, float, float, float]]:
    """One house with an overhanging roof. Returns its window rectangles."""
    body = (18, 22, 44, 255)
    roof = (9, 12, 28, 255)
    top = ground - height
    draw.rectangle((x, top, x + width, ground + 40), fill=body)
    eave = width * 0.18
    draw.polygon(
        [(x - eave, top + 6), (x + width / 2, top - height * 0.42), (x + width + eave, top + 6)],
        fill=roof,
    )
    windows = []
    columns = max(1, int(width // 46))
    for column in range(columns):
        wx = x + width * (column + 0.5) / columns - 9
        windows.append((wx, top + height * 0.38, wx + 18, top + height * 0.38 + 26))
    return windows


def village() -> Image.Image:
    """Hills and a sleeping village as silhouettes, transparent where the sky shows."""
    rng = _rng(2)
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    _fill_below(draw, _ridge(rng, 1330, 70), (26, 32, 70, 255))
    middle = _ridge(rng, 1470, 55)
    _fill_below(draw, middle, (15, 20, 46, 255))

    windows: list[tuple[float, float, float, float]] = []
    x = 30.0
    while x < WIDTH - 90:
        width = float(rng.integers(70, 150))
        height = float(rng.integers(70, 150))
        ground = float(middle[int(min(x + width / 2, WIDTH - 1))]) + 14
        windows.extend(_house(draw, x, ground, width, height))
        x += width + float(rng.integers(24, 90))

    lit = [window for window in windows if rng.random() < 0.45]
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for left, top, right, bottom in lit:
        glow_draw.rectangle(
            (left - 10, top - 10, right + 10, bottom + 10), fill=(255, 186, 96, 120)
        )
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(12)))
    draw = ImageDraw.Draw(image)
    for left, top, right, bottom in lit:
        draw.rectangle((left, top, right, bottom), fill=(255, 204, 128, 255))

    _fill_below(draw, _ridge(rng, 1690, 40), (6, 8, 20, 255))
    return image


# --- scroll --------------------------------------------------------------------------


def paper(width: int = 800, height: int = 1090) -> Image.Image:
    """A sheet of parchment with soft mottling, fibres and darker, slightly ragged edges."""
    rng = _rng(3)
    base = np.array([230.0, 211.0, 163.0])
    coarse = rng.normal(0, 1, (height // 40 + 2, width // 40 + 2))
    mottling = np.asarray(
        Image.fromarray(((coarse - coarse.min()) / np.ptp(coarse) * 255).astype(np.uint8)).resize(
            (width, height), Image.Resampling.BICUBIC
        ),
        dtype=float,
    )
    grain = rng.normal(0, 3.0, (height, width))
    shade = (mottling - 128) / 128 * 9 + grain

    yy, xx = np.mgrid[0:height, 0:width]
    edge = np.minimum.reduce([xx, width - 1 - xx, yy, height - 1 - yy]).astype(float)
    vignette = np.clip(1 - edge / 110, 0, 1) ** 1.6 * 34
    pixels = (
        base[None, None, :] + shade[:, :, None] - vignette[:, :, None] * np.array([1.0, 1.15, 1.5])
    )
    image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB").convert("RGBA")

    fibres = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(fibres)
    for _ in range(260):
        x, y = float(rng.uniform(0, width)), float(rng.uniform(0, height))
        angle = float(rng.normal(0, 0.5))
        length = float(rng.uniform(8, 34))
        end = (x + math.cos(angle) * length, y + math.sin(angle) * length)
        draw.line(((x, y), end), fill=(122, 96, 58, int(rng.integers(18, 46))), width=1)
    image = Image.alpha_composite(image, fibres)

    mask = Image.new("L", (width, height), 255)
    mask_draw = ImageDraw.Draw(mask)
    for side in (0, width):
        y = 0.0
        while y < height:
            bite = float(rng.uniform(0.6, 3.0))
            reach = float(rng.uniform(5, 22))
            mask_draw.ellipse((side - bite, y - reach, side + bite, y + reach), fill=0)
            y += float(rng.uniform(14, 70))
    image.putalpha(mask.filter(ImageFilter.GaussianBlur(0.8)))
    return image


def roller(width: int = 880, height: int = 64) -> Image.Image:
    """The wooden rod a scroll hangs from, with a knob at each end."""
    rng = _rng(4)
    y = np.linspace(-1, 1, height)
    roundness = np.sqrt(np.clip(1 - y**2, 0, 1))
    wood = np.array([108.0, 70.0, 40.0])
    column = wood[None, :] * (0.38 + 0.72 * roundness[:, None])
    pixels = np.repeat(column[:, None, :], width, axis=1)
    pixels += rng.normal(0, 4, (1, width, 1)) + rng.normal(0, 1.5, (height, width, 1))
    image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB").convert("RGBA")

    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((26, 8, width - 26, height - 8), radius=22, fill=255)
    for left in (0, width - 44):
        draw.rounded_rectangle((left, 0, left + 44, height - 1), radius=18, fill=255)
    image.putalpha(mask)

    knobs = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    knob_draw = ImageDraw.Draw(knobs)
    for left in (0, width - 44):
        knob_draw.rounded_rectangle(
            (left, 0, left + 44, height - 1), radius=18, fill=(36, 22, 14, 110)
        )
    return Image.alpha_composite(image, knobs)


# --- sprites -------------------------------------------------------------------------


def lantern(width: int = 240, height: int = 360) -> Image.Image:
    """A paper lantern with a warm glow."""
    scale = 3
    big = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    cx = width * scale / 2
    body = (cx - 78 * scale, 96 * scale, cx + 78 * scale, 300 * scale)

    halo = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse(
        (cx - 84 * scale, 96 * scale, cx + 84 * scale, 300 * scale), fill=(255, 170, 70, 110)
    )
    # The glow must fade out before the edge of the sprite, or its box would show.
    big = Image.alpha_composite(big, halo.filter(ImageFilter.GaussianBlur(12 * scale)))
    draw = ImageDraw.Draw(big)

    draw.line(((cx, 0), (cx, 84 * scale)), fill=(20, 18, 24, 255), width=3 * scale)
    draw.ellipse(body, fill=(246, 150, 54, 255))
    inner = (cx - 52 * scale, 122 * scale, cx + 52 * scale, 274 * scale)
    light = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(light).ellipse(inner, fill=(255, 226, 150, 235))
    big = Image.alpha_composite(big, light.filter(ImageFilter.GaussianBlur(18 * scale)))
    draw = ImageDraw.Draw(big)

    for offset in (-52, -26, 0, 26, 52):
        bulge = abs(offset) / 52
        draw.arc(
            (
                cx + (offset - 30 + 30 * bulge) * scale,
                96 * scale,
                cx + (offset + 30 - 30 * bulge) * scale,
                300 * scale,
            ),
            start=90 if offset < 0 else 270,
            end=270 if offset < 0 else 90,
            fill=(150, 70, 20, 150),
            width=2 * scale,
        )
    for top in (84, 292):
        draw.rounded_rectangle(
            (cx - 40 * scale, top * scale, cx + 40 * scale, (top + 20) * scale),
            radius=6 * scale,
            fill=(28, 20, 22, 255),
        )
    draw.line(((cx, 312 * scale), (cx, 352 * scale)), fill=(150, 40, 30, 255), width=5 * scale)
    return big.resize((width, height), Image.Resampling.LANCZOS)


def moon(size: int = 320) -> Image.Image:
    """A pale moon with a few soft craters and a halo."""
    rng = _rng(5)
    scale = 3
    full = size * scale
    image = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    halo = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse(
        (full * 0.1, full * 0.1, full * 0.9, full * 0.9), fill=(220, 226, 255, 90)
    )
    image = Image.alpha_composite(image, halo.filter(ImageFilter.GaussianBlur(full * 0.06)))
    draw = ImageDraw.Draw(image)
    disc = (full * 0.2, full * 0.2, full * 0.8, full * 0.8)
    draw.ellipse(disc, fill=(238, 233, 210, 255))

    craters = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    crater_draw = ImageDraw.Draw(craters)
    for _ in range(9):
        angle = float(rng.uniform(0, 2 * math.pi))
        distance = float(rng.uniform(0, full * 0.22))
        radius = float(rng.uniform(full * 0.018, full * 0.06))
        x, y = full / 2 + math.cos(angle) * distance, full / 2 + math.sin(angle) * distance
        crater_draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius), fill=(196, 190, 170, 150)
        )
    image = Image.alpha_composite(image, craters.filter(ImageFilter.GaussianBlur(full * 0.008)))
    return image.resize((size, size), Image.Resampling.LANCZOS)


def pin(size: int = 96) -> Image.Image:
    """The pin that holds a tag: a red head with a highlight and a soft shadow."""
    scale = 4
    full = size * scale
    image = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        (full * 0.3, full * 0.36, full * 0.84, full * 0.9), fill=(0, 0, 0, 120)
    )
    image = Image.alpha_composite(image, shadow.filter(ImageFilter.GaussianBlur(full * 0.05)))
    draw = ImageDraw.Draw(image)
    draw.ellipse((full * 0.2, full * 0.18, full * 0.74, full * 0.72), fill=(176, 36, 28, 255))
    draw.ellipse((full * 0.26, full * 0.22, full * 0.66, full * 0.62), fill=(212, 58, 44, 255))
    draw.ellipse((full * 0.34, full * 0.28, full * 0.46, full * 0.4), fill=(255, 190, 170, 230))
    return image.resize((size, size), Image.Resampling.LANCZOS)


# --- sounds --------------------------------------------------------------------------


def _band(noise: np.ndarray, low_hz: float, high_hz: float) -> np.ndarray:
    """Keep only the frequencies between low and high."""
    spectrum = np.fft.rfft(noise)
    frequencies = np.fft.rfftfreq(len(noise), 1 / SAMPLE_RATE)
    spectrum[(frequencies < low_hz) | (frequencies > high_hz)] = 0
    return np.fft.irfft(spectrum, len(noise))


def _time(seconds: float) -> np.ndarray:
    return np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE


def paper_unroll() -> np.ndarray:
    t = _time(0.7)
    noise = _band(_rng(11).standard_normal(len(t)), 900, 7000)
    envelope = np.sin(np.pi * t / t[-1]) ** 1.5
    crackle = 0.6 + 0.4 * np.abs(np.sin(2 * np.pi * 27 * t + np.sin(2 * np.pi * 3 * t) * 4))
    unrolled: np.ndarray = noise * envelope * crackle
    return unrolled


def stamp() -> np.ndarray:
    t = _time(0.28)
    thud = np.sin(2 * np.pi * 85 * t) * np.exp(-t * 22)
    click = _band(_rng(12).standard_normal(len(t)), 300, 2500) * np.exp(-t * 160) * 0.5
    return thud + click


def pin_hit() -> np.ndarray:
    t = _time(0.12)
    tick = np.sin(2 * np.pi * 2200 * t) * np.exp(-t * 70)
    click = _band(_rng(13).standard_normal(len(t)), 2000, 9000) * np.exp(-t * 300) * 0.4
    return tick * 0.7 + click


def smoke() -> np.ndarray:
    t = _time(0.8)
    noise = _band(_rng(14).standard_normal(len(t)), 180, 2200)
    whoosh: np.ndarray = noise * np.sin(np.pi * t / t[-1]) ** 2
    return whoosh


def slam() -> np.ndarray:
    t = _time(0.45)
    frequency = 45 + 95 * np.exp(-t * 14)
    body = np.sin(2 * np.pi * np.cumsum(frequency) / SAMPLE_RATE) * np.exp(-t * 9)
    burst = _band(_rng(15).standard_normal(len(t)), 200, 5000) * np.exp(-t * 90) * 0.6
    return body + burst


def _write_wav(path: Path, samples: np.ndarray, peak: float = 0.7) -> None:
    """Write mono 16-bit audio, scaled so its loudest sample sits at `peak` of full scale."""
    fade = min(len(samples) // 20, 220)
    samples = samples.copy()
    samples[:fade] *= np.linspace(0, 1, fade)
    samples[-fade:] *= np.linspace(1, 0, fade)
    scaled = samples / np.max(np.abs(samples)) * peak
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(SAMPLE_RATE)
        file.writeframes((scaled * 32767).astype("<i2").tobytes())


# --- build ---------------------------------------------------------------------------

IMAGES = {
    "backgrounds/sky.png": sky,
    "backgrounds/village.png": village,
    "scroll/paper.png": paper,
    "scroll/roller.png": roller,
    "sprites/lantern.png": lantern,
    "sprites/moon.png": moon,
    "sprites/pin.png": pin,
}
SOUNDS = {
    "sounds/paper_unroll.wav": paper_unroll,
    "sounds/stamp.wav": stamp,
    "sounds/pin_hit.wav": pin_hit,
    "sounds/smoke.wav": smoke,
    "sounds/slam.wav": slam,
}


def build(assets: Path = ASSETS) -> list[Path]:
    """Write every image and sound. Returns the files written."""
    written = []
    for name, make_image in IMAGES.items():
        path = assets / name
        path.parent.mkdir(parents=True, exist_ok=True)
        make_image().save(path, optimize=True)
        written.append(path)
    for name, make_sound in SOUNDS.items():
        path = assets / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_wav(path, make_sound())
        written.append(path)
    return written


if __name__ == "__main__":
    for written_path in build():
        sys.stdout.write(f"wrote {written_path.relative_to(ASSETS.parent)}\n")
