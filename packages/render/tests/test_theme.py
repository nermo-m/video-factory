"""The night_scrolls theme (decision D10): assets, layout and capabilities.

Rule 2 of the public repository: every asset is original or permissively licensed and
listed in ASSETS.md. scripts/check_assets.py enforces the listing for the whole repository.
"""

from __future__ import annotations

import copy
import json
import wave
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageFont

from packages.core import schemas
from packages.render.theme import Theme, check_capabilities, load_theme

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid"


@pytest.fixture(scope="module")
def theme() -> Theme:
    return load_theme("night_scrolls")


def spec(name: str = "all_scene_kinds.json") -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return loaded


# --- loading -------------------------------------------------------------------------


def test_d10_the_only_theme_is_night_scrolls(theme: Theme) -> None:
    assert theme.name == "night_scrolls"
    assert theme.root == ROOT / "packages" / "render" / "theme" / "night_scrolls"
    with pytest.raises(KeyError, match="There is no theme named 'daylight'"):
        load_theme("daylight")


def test_theme_names_cannot_escape_the_theme_folder() -> None:
    for name in ("../core", "night_scrolls/..", "", "Night Scrolls"):
        with pytest.raises(KeyError):
            load_theme(name)


# --- capabilities --------------------------------------------------------------------


def test_capabilities_list_every_scene_kind_and_overlay_type_the_schema_allows(
    theme: Theme,
) -> None:
    schema = schemas.load_schema("episode_spec")
    scene_kinds = schema["$defs"]["scene"]["properties"]["kind"]["enum"]
    overlay_types = schema["$defs"]["overlay"]["properties"]["type"]["enum"]

    assert theme.capabilities["theme"] == "night_scrolls"
    assert theme.capabilities["scene_kinds"] == scene_kinds
    assert theme.capabilities["overlay_types"] == overlay_types


def test_capabilities_list_sprites_cues_transitions_and_text_styles(theme: Theme) -> None:
    capabilities = theme.capabilities

    assert set(capabilities) == {
        "theme",
        "scene_kinds",
        "text_styles",
        "overlay_types",
        "stamp_colors",
        "sprites",
        "sound_cues",
        "transitions",
    }
    assert capabilities["text_styles"] == ["slam", "slam_accent"]
    assert capabilities["stamp_colors"] == ["ink", "red"]
    assert capabilities["sprites"] == {"lantern": ["sway", "rise"], "moon": ["rise", "glow"]}
    assert capabilities["sound_cues"] == ["paper_unroll", "stamp", "pin_hit", "smoke", "slam"]
    assert capabilities["transitions"] == ["smoke", "cut"]


def test_everything_in_capabilities_has_something_behind_it(theme: Theme) -> None:
    capabilities = theme.capabilities

    assert set(capabilities["sound_cues"]) == set(theme.sounds)
    assert set(capabilities["sprites"]) == set(theme.sprites)
    assert set(capabilities["stamp_colors"]) == set(theme.config["stamp_colors"])
    assert set(capabilities["text_styles"]) == set(theme.config["text_styles"])


def test_the_design_fixtures_only_ask_for_what_the_theme_can_draw(theme: Theme) -> None:
    for name in ("all_scene_kinds.json", "design_doc_example.json", "minimal.json"):
        assert check_capabilities(spec(name), theme.capabilities) == [], name


def test_a_spec_cannot_ask_for_something_the_renderer_cannot_draw(theme: Theme) -> None:
    authored = copy.deepcopy(spec())
    authored["scenes"][0]["text"][0]["style"] = "neon"
    authored["scenes"][0]["transition_out"] = "wipe"
    authored["scenes"][1]["overlays"][0] = {"type": "stamp", "content": "X", "color": "gold"}
    authored["scenes"][1]["overlays"][1] = {"type": "sprite", "name": "dragon"}
    authored["scenes"][1]["sound"][0]["cue_id"] = "explosion"

    problems = [str(problem) for problem in check_capabilities(authored, theme.capabilities)]

    assert problems == [
        "/scenes/0/text/0/style: the theme has no text style 'neon'. It has: slam, slam_accent",
        "/scenes/0/transition_out: the theme has no transition 'wipe'. It has: smoke, cut",
        "/scenes/1/overlays/0/color: the theme has no stamp colour 'gold'. It has: ink, red",
        "/scenes/1/overlays/1/name: the theme has no sprite 'dragon'. It has: lantern, moon",
        "/scenes/1/sound/0/cue_id: the theme has no sound cue 'explosion'. "
        "It has: paper_unroll, stamp, pin_hit, smoke, slam",
    ]


def test_a_sprite_can_only_do_what_it_knows(theme: Theme) -> None:
    authored = copy.deepcopy(spec())
    authored["scenes"][1]["overlays"][1] = {"type": "sprite", "name": "moon", "action": "sway"}

    problems = [str(problem) for problem in check_capabilities(authored, theme.capabilities)]

    assert problems == [
        "/scenes/1/overlays/1/action: the sprite 'moon' cannot 'sway'. It can: rise, glow"
    ]


def test_a_spec_for_another_theme_is_rejected(theme: Theme) -> None:
    authored = copy.deepcopy(spec("minimal.json"))
    authored["theme"] = "daylight"

    problems = [str(problem) for problem in check_capabilities(authored, theme.capabilities)]

    assert problems == ["/theme: this is the theme 'night_scrolls', the spec asks for 'daylight'"]


# --- assets --------------------------------------------------------------------------


def test_rn10_fonts_are_bundled_and_load_by_path(theme: Theme) -> None:
    assert set(theme.fonts) == {"display", "body", "hand"}
    for role, path in theme.fonts.items():
        assert path.is_file(), f"the {role} font is missing"
        assert theme.root in path.parents, "fonts come from the repository, never the system"
        font = ImageFont.truetype(str(path), 64)
        assert font.getlength("SMALL STEPS") > 100


def test_every_font_ships_with_its_licence_text(theme: Theme) -> None:
    for path in theme.fonts.values():
        family = path.name.split("-")[0]
        licence = path.with_name(f"{family}-OFL.txt")
        assert "SIL Open Font License" in licence.read_text(encoding="utf-8")


def test_backgrounds_cover_the_full_frame(theme: Theme) -> None:
    assert [layer.name for layer in theme.backgrounds] == ["sky.png", "village.png"]
    sky, village = (Image.open(path) for path in theme.backgrounds)

    assert sky.size == village.size == (1080, 1920)
    assert sky.mode == "RGB"
    # The village is drawn over the sky, so it must be see-through above the rooftops.
    assert village.mode == "RGBA"
    alpha = village.getchannel("A")
    assert alpha.getpixel((540, 100)) == 0
    assert alpha.getpixel((540, 1900)) == 255


def test_scroll_parts_and_sprites_are_transparent_images(theme: Theme) -> None:
    files = {**theme.scroll, **theme.sprites}

    assert set(theme.scroll) == {"paper", "roller"}
    assert set(theme.sprites) == {"lantern", "moon"}
    for name, path in files.items():
        with Image.open(path) as image:
            assert image.mode == "RGBA", name
            assert min(image.size) >= 64, name
    with Image.open(theme.root / "assets" / "sprites" / "pin.png") as pin:
        assert pin.mode == "RGBA"


def test_sound_cues_are_short_mono_wav_files(theme: Theme) -> None:
    for cue_id, path in theme.sounds.items():
        with wave.open(str(path), "rb") as sound:
            assert sound.getframerate() == 44100, cue_id
            assert sound.getnchannels() == 1, cue_id
            assert sound.getsampwidth() == 2, cue_id
            seconds = sound.getnframes() / sound.getframerate()
            assert 0.05 <= seconds <= 1.5, cue_id
            frames = sound.readframes(sound.getnframes())
        assert any(frames), f"{cue_id} is silent"


def test_every_theme_asset_file_is_used_by_the_theme(theme: Theme) -> None:
    used = {
        *theme.fonts.values(),
        *theme.backgrounds,
        *theme.scroll.values(),
        *theme.sprites.values(),
        *theme.sounds.values(),
        theme.root / "assets" / "sprites" / "pin.png",
    }
    on_disk = {
        path
        for path in (theme.root / "assets").rglob("*")
        if path.is_file() and not path.name.endswith("-OFL.txt")
    }

    assert on_disk == used


# --- layout --------------------------------------------------------------------------


def test_rn07_text_stays_out_of_the_bottom_15_and_right_12_percent(theme: Theme) -> None:
    safe = theme.config["layout"]["safe_area"]

    assert safe["bottom"] >= 0.15
    assert safe["right"] >= 0.12
    width, height = 1080, 1920
    for name in ("scroll", "captions", "slam"):
        box = theme.config["layout"][name]
        assert 0 <= box["x"] < box["x"] + box["w"] <= round(width * (1 - safe["right"])), name
        assert 0 <= box["y"] < box["y"] + box["h"] <= round(height * (1 - safe["bottom"])), name


def test_the_palette_is_complete_and_written_as_hex_colours(theme: Theme) -> None:
    palette = theme.config["palette"]

    assert {"night", "paper", "ink", "accent", "text"} <= set(palette)
    for name, value in palette.items():
        assert isinstance(value, str), name
        assert len(value) == 7, name
        assert value.startswith("#"), name
        int(value[1:], 16)


def test_rule2_every_theme_asset_is_registered() -> None:
    registry = (ROOT / "ASSETS.md").read_text(encoding="utf-8")

    for needle in (
        "packages/render/theme/night_scrolls/assets/fonts/Anton-Regular.ttf",
        "packages/render/theme/night_scrolls/assets/fonts/Inter-Variable.ttf",
        "packages/render/theme/night_scrolls/assets/fonts/Kalam-Bold.ttf",
        "packages/render/theme/night_scrolls/assets/backgrounds/*.png",
        "packages/render/theme/night_scrolls/assets/sounds/*.wav",
    ):
        assert needle in registry
