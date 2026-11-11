"""The resolver: authored spec plus voice timings to resolved spec (FR-04, section 5.2)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from packages.core import schemas
from packages.render.resolver import (
    AssetFile,
    DurationError,
    NarrationTiming,
    ResolveError,
    WordTiming,
    resolve,
)

FIXTURES = schemas.SCHEMA_DIR / "fixtures" / "episode_spec" / "valid"


def load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return loaded


def timing(text: str, duration_s: float, scene_id: str = "scene") -> NarrationTiming:
    """Voice result with every word the same length, which keeps the arithmetic readable."""
    words = text.split()
    step = duration_s / len(words)
    return NarrationTiming(
        audio_file=f"episodes/ep/voice/{scene_id}.wav",
        duration_s=duration_s,
        words=[
            WordTiming(word, round(i * step, 6), round((i + 1) * step, 6))
            for i, word in enumerate(words)
        ],
    )


def scene(scene_id: str, narration: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": scene_id,
        "kind": "title",
        "narration": narration,
        "text": [{"content": "TEXT", "style": "slam"}],
        **fields,
    }


def spec(
    scenes: list[dict[str, Any]], target_duration_s: float = 10, **fields: Any
) -> dict[str, Any]:
    return {
        "spec_version": "2.0",
        "episode_id": "ep_test",
        "format": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "target_duration_s": target_duration_s,
        },
        "theme": "night_scrolls",
        "voice": {"voice_id": "bm_george", "speed": 1.0},
        "seed": 3,
        "scenes": scenes,
        "claims": [],
        "assets": [],
        **fields,
    }


def voice_for(
    authored: dict[str, Any], seconds_per_word: float = 0.5
) -> dict[str, NarrationTiming]:
    return {
        item["id"]: timing(
            item["narration"], len(item["narration"].split()) * seconds_per_word, item["id"]
        )
        for item in authored["scenes"]
        if item["narration"]
    }


TEN_WORDS = "one two three four five six seven eight nine ten"


# --- scene times ---------------------------------------------------------------------


def test_fr04_scene_length_is_narration_plus_the_default_pads() -> None:
    authored = spec([scene("s01", TEN_WORDS), scene("s02", TEN_WORDS)], target_duration_s=11.4)

    resolved = resolve(authored, voice_for(authored), {})

    first, second = resolved["scenes"]
    # 0.3 before, 5.0 of narration, 0.4 after.
    assert (first["start_s"], first["duration_s"]) == (0, 5.7)
    assert (second["start_s"], second["duration_s"]) == (5.7, 5.7)
    assert resolved["duration_s"] == 11.4
    assert first["narration"]["start_s"] == 0.3
    assert second["narration"]["start_s"] == 6.0
    assert first["narration"]["duration_s"] == 5.0
    assert first["narration"]["audio_file"] == "episodes/ep/voice/s01.wav"


def test_fr04_pads_can_be_set_per_scene() -> None:
    authored = spec(
        [scene("s01", TEN_WORDS, pad_before_s=1.0, pad_after_s=2.0)], target_duration_s=8
    )

    resolved = resolve(authored, voice_for(authored), {})

    assert resolved["scenes"][0]["duration_s"] == 8.0
    assert resolved["scenes"][0]["narration"]["start_s"] == 1.0


def test_fr04_a_fixed_duration_overrides_the_pads() -> None:
    authored = spec([scene("s01", TEN_WORDS, duration_s=9.0)], target_duration_s=9)

    resolved = resolve(authored, voice_for(authored), {})

    assert resolved["scenes"][0]["duration_s"] == 9.0
    assert resolved["scenes"][0]["narration"]["start_s"] == 0.3


def test_fr04_a_fixed_duration_must_fit_the_narration() -> None:
    authored = spec([scene("s01", TEN_WORDS, duration_s=4.0)], target_duration_s=4)

    with pytest.raises(ResolveError) as raised:
        resolve(authored, voice_for(authored), {})

    assert [str(problem) for problem in raised.value.problems] == [
        "/scenes/0/duration_s: the scene is set to 4 s but its narration needs 5.3 s "
        "(0.3 s before it and 5 s of speech)"
    ]


def test_fr04_a_silent_scene_needs_no_voice_and_has_no_audio() -> None:
    authored = spec(
        [scene("s01", "", duration_s=0.6), scene("s02", TEN_WORDS)], target_duration_s=6.3
    )

    resolved = resolve(authored, voice_for(authored), {})

    silent = resolved["scenes"][0]
    assert silent["duration_s"] == 0.6
    assert silent["narration"] == {
        "text": "",
        "audio_file": None,
        "start_s": 0,
        "duration_s": 0,
        "words": [],
    }
    assert resolved["scenes"][1]["start_s"] == 0.6


def test_fr04_an_outro_holds_its_closing_line() -> None:
    held = scene("s01", TEN_WORDS, kind="outro", hold_s=1.5)
    default = scene("s02", TEN_WORDS, kind="outro")
    authored = spec([held, default], target_duration_s=14.9)

    resolved = resolve(authored, voice_for(authored), {})

    # 0.3 + 5.0 + 0.4, then the hold.
    assert resolved["scenes"][0]["duration_s"] == 7.2
    assert resolved["scenes"][0]["hold_s"] == 1.5
    # The design asks for the closing line to be held for 2 seconds.
    assert resolved["scenes"][1]["duration_s"] == 7.7
    assert resolved["scenes"][1]["hold_s"] == 2.0


def test_fr04_word_times_become_absolute() -> None:
    authored = spec(
        [scene("s01", "alpha beta"), scene("s02", "gamma delta")], target_duration_s=3.4
    )

    resolved = resolve(authored, voice_for(authored), {})

    assert resolved["scenes"][1]["narration"]["words"] == [
        {"text": "gamma", "start_s": 2.0, "end_s": 2.5},
        {"text": "delta", "start_s": 2.5, "end_s": 3.0},
    ]


# --- the four cue types --------------------------------------------------------------


def cue_time(cue: dict[str, float] | None, **scene_fields: Any) -> float:
    """Resolve one text item with this cue in the second of two 5.7 second scenes."""
    item: dict[str, Any] = {"content": "NOW", "style": "slam"}
    if cue is not None:
        item["cue"] = cue
    authored = spec(
        [scene("s01", TEN_WORDS), scene("s02", TEN_WORDS, text=[item], **scene_fields)],
        target_duration_s=11.4,
    )
    resolved = resolve(authored, voice_for(authored), {})
    at_s: float = resolved["scenes"][1]["text"][0]["at_s"]
    return at_s


def test_fr04_word_cue_fires_when_that_word_starts_counting_from_zero() -> None:
    # Scene two starts at 5.7 and its narration at 6.0. Each word lasts 0.5 s.
    assert cue_time({"word": 0}) == 6.0
    assert cue_time({"word": 7}) == 9.5
    assert cue_time({"word": 9}) == 10.5


def test_fr04_scene_start_cue_counts_from_the_start_of_its_scene() -> None:
    assert cue_time({"scene_start_s": 0}) == 5.7
    assert cue_time({"scene_start_s": 0.1}) == 5.8


def test_fr04_after_narration_cue_counts_from_the_end_of_the_speech() -> None:
    # Narration runs from 6.0 to 11.0.
    assert cue_time({"after_narration_s": 0}) == 11.0
    assert cue_time({"after_narration_s": 0.2}) == 11.2


def test_fr04_absolute_cue_is_a_time_in_the_video() -> None:
    assert cue_time({"at_s": 8.25}) == 8.25


def test_fr04_an_event_without_a_cue_happens_when_its_scene_starts() -> None:
    assert cue_time(None) == 5.7


def test_fr04_cues_work_the_same_on_overlays_sound_and_steps() -> None:
    authored = spec(
        [
            {
                "id": "s01",
                "kind": "steps",
                "narration": TEN_WORDS,
                "steps": [{"text": "First", "cue": {"word": 2}}, {"text": "Second"}],
                "overlays": [
                    {"type": "tag", "lines": ["A"], "cue": {"scene_start_s": 1}},
                    {"type": "stamp", "content": "B", "cue": {"after_narration_s": 0.1}},
                    {"type": "sprite", "name": "lantern", "cue": {"at_s": 2}},
                ],
                "sound": [
                    {"cue_id": "paper_unroll", "cue": {"word": 4}},
                    {"cue_id": "thud", "gain_db": -6},
                ],
            }
        ],
        target_duration_s=5.7,
    )

    resolved = resolve(authored, voice_for(authored), {})["scenes"][0]

    assert resolved["steps"] == [{"text": "First", "at_s": 1.3}, {"text": "Second", "at_s": 0}]
    assert resolved["overlays"] == [
        {"type": "tag", "lines": ["A"], "side": "left", "at_s": 1.0},
        {"type": "stamp", "content": "B", "at_s": 5.4},
        {"type": "sprite", "name": "lantern", "at_s": 2.0},
    ]
    assert resolved["sound"] == [
        {"cue_id": "paper_unroll", "at_s": 2.3, "gain_db": 0},
        {"cue_id": "thud", "at_s": 0, "gain_db": -6},
    ]


# --- duration tolerance --------------------------------------------------------------


def three_scenes(target: float) -> dict[str, Any]:
    return spec(
        [
            scene("s01_hook", "one two"),
            scene("s02_story", TEN_WORDS),
            scene("s03_close", "one two three four"),
        ],
        target_duration_s=target,
    )


def test_fr04_total_within_two_seconds_of_the_target_is_accepted() -> None:
    # The three scenes last 1.7 + 5.7 + 2.7 = 10.1 seconds.
    for target in (8.1, 10.1, 12.1):
        authored = three_scenes(target)
        assert resolve(authored, voice_for(authored), {})["duration_s"] == 10.1


def test_fr04_too_long_names_the_scenes_to_shorten_longest_first() -> None:
    authored = three_scenes(8.0)

    with pytest.raises(DurationError) as raised:
        resolve(authored, voice_for(authored), {})

    error = raised.value
    assert (error.total_s, error.target_s, error.difference_s) == (10.1, 8.0, 2.1)
    assert error.scenes == [("s02_story", 5.7), ("s03_close", 2.7), ("s01_hook", 1.7)]
    assert str(error) == (
        "The video is 10.1 s long, 2.1 s more than the 8 s target (2 s is allowed). "
        "Shorten these scenes, longest first: "
        "s02_story (5.7 s), s03_close (2.7 s), s01_hook (1.7 s)."
    )
    assert isinstance(error, ResolveError)


def test_fr04_too_short_names_the_scenes_to_lengthen_shortest_first() -> None:
    authored = three_scenes(12.2)

    with pytest.raises(DurationError) as raised:
        resolve(authored, voice_for(authored), {})

    assert raised.value.scenes[0] == ("s01_hook", 1.7)
    assert str(raised.value) == (
        "The video is 10.1 s long, 2.1 s less than the 12.2 s target (2 s is allowed). "
        "Lengthen these scenes, shortest first: "
        "s01_hook (1.7 s), s03_close (2.7 s), s02_story (5.7 s)."
    )


# --- what a schema cannot check ------------------------------------------------------


def test_references_and_timings_are_all_checked_and_reported_together() -> None:
    authored = spec(
        [
            scene(
                "s01", TEN_WORDS, text=[{"content": "LATE", "style": "slam", "cue": {"word": 10}}]
            ),
            {
                "id": "s01",
                "kind": "scroll",
                "title": "T",
                "narration": TEN_WORDS,
                "visual": {"asset_id": "a_missing"},
                "overlays": [{"type": "stamp", "content": "X", "cue": {"after_narration_s": 0.7}}],
            },
            {
                "id": "s03",
                "kind": "stat",
                "narration": "three more words",
                "stat": {"value": "7 in 10", "label": "kept going", "claim_id": "c_missing"},
            },
        ],
        target_duration_s=15,
    )
    voice = voice_for(authored)
    del voice["s03"]

    with pytest.raises(ResolveError) as raised:
        resolve(authored, voice, {})

    assert [str(problem) for problem in raised.value.problems] == [
        "/scenes/0/text/0/cue: word 10 does not exist, the narration has 10 words (0 to 9)",
        "/scenes/1/id: the id 's01' is already used by scene 0",
        "/scenes/1/visual/asset_id: there is no asset 'a_missing' in this spec",
        "/scenes/1/overlays/0/cue: 11.7 s is outside this scene, which runs from 5.7 s to 11.4 s",
        "/scenes/2: there are no voice timings for this scene's narration",
        "/scenes/2/stat/claim_id: there is no claim 'c_missing' in this spec",
    ]


def test_voice_timings_must_match_the_narration_words() -> None:
    authored = spec([scene("s01", TEN_WORDS)])
    voice = {"s01": timing("only three words", 5.0, "s01")}

    with pytest.raises(ResolveError) as raised:
        resolve(authored, voice, {})

    assert [str(problem) for problem in raised.value.problems] == [
        "/scenes/0: the voice timings have 3 words but the narration has 10. "
        "Generate the voice for this scene again."
    ]


def test_an_absolute_cue_must_fall_inside_its_own_scene() -> None:
    authored = spec(
        [scene("s01", TEN_WORDS, text=[{"content": "X", "style": "slam", "cue": {"at_s": 9}}])],
        target_duration_s=5.7,
    )

    with pytest.raises(
        ResolveError, match=r"9 s is outside this scene, which runs from 0 s to 5\.7 s"
    ):
        resolve(authored, voice_for(authored), {})


def with_asset(**asset_fields: Any) -> dict[str, Any]:
    asset = {
        "id": "a_hill_dawn",
        "kind": "image",
        "origin": "generated",
        "prompt": "a hill at dawn",
        "contains_third_party_ip": False,
        "rights_status": "cleared",
        **asset_fields,
    }
    scroll = {
        "id": "s01",
        "kind": "scroll",
        "title": "THE CLIMB",
        "narration": TEN_WORDS,
        "visual": {"asset_id": "a_hill_dawn", "clip": True},
    }
    return spec([scroll], target_duration_s=5.7, assets=[asset])


def test_fr05_every_asset_needs_its_file_before_rendering() -> None:
    authored = with_asset()

    with pytest.raises(ResolveError) as raised:
        resolve(authored, voice_for(authored), {})

    assert [str(problem) for problem in raised.value.problems] == [
        "/assets/0: the asset 'a_hill_dawn' has no file yet. Generate it, upload it or pick "
        "one from the library."
    ]


def test_assets_carry_their_file_licence_and_clip() -> None:
    authored = with_asset(tags=["hill"])
    files = {
        "a_hill_dawn": AssetFile(
            file="assets/a_hill_dawn/v2.png", licence="MIT", clip_file="assets/a_hill_dawn/v2.mp4"
        )
    }

    resolved = resolve(authored, voice_for(authored), files)

    assert resolved["assets"] == [
        {
            "id": "a_hill_dawn",
            "kind": "image",
            "origin": "generated",
            "prompt": "a hill at dawn",
            "licence": "MIT",
            "contains_third_party_ip": False,
            "rights_status": "cleared",
            "tags": ["hill"],
            "file": "assets/a_hill_dawn/v2.png",
            "clip_file": "assets/a_hill_dawn/v2.mp4",
        }
    ]
    assert resolved["scenes"][0]["visual"] == {"asset_id": "a_hill_dawn", "clip": True}


def test_an_asset_without_any_licence_is_reported() -> None:
    authored = with_asset()
    files = {"a_hill_dawn": AssetFile(file="assets/a_hill_dawn/v1.png")}

    with pytest.raises(ResolveError, match="the asset 'a_hill_dawn' has no licence recorded"):
        resolve(authored, voice_for(authored), files)


def test_the_authored_licence_is_used_when_the_file_brings_none() -> None:
    authored = with_asset(licence="CC0-1.0")
    files = {"a_hill_dawn": AssetFile(file="assets/a_hill_dawn/v1.png")}

    assert resolve(authored, voice_for(authored), files)["assets"][0]["licence"] == "CC0-1.0"


# --- the result ----------------------------------------------------------------------


def test_an_invalid_authored_spec_is_rejected_before_anything_else() -> None:
    authored = spec([scene("s01", TEN_WORDS)])
    del authored["seed"]

    with pytest.raises(schemas.SchemaValidationError):
        resolve(authored, voice_for(authored), {})


def test_the_design_document_example_resolves_to_a_valid_resolved_spec() -> None:
    authored = load("design_doc_example.json")
    authored["format"]["target_duration_s"] = 12
    files = {"a_hill_dawn": AssetFile(file="assets/a_hill_dawn/v1.png", licence="MIT")}

    resolved = resolve(authored, voice_for(authored), files)

    assert schemas.validate("resolved_spec", resolved) == []
    hook, story = resolved["scenes"]
    # "To everyone who keeps putting it off. Small steps still count.": word 7 is "Small".
    assert hook["narration"]["words"][7]["text"] == "Small"
    assert hook["text"][0] == {"content": "SMALL STEPS", "style": "slam", "at_s": 3.8}
    assert hook["text"][1]["at_s"] == 4.8
    assert story["overlays"][0]["at_s"] == round(story["narration"]["start_s"] + 2.5, 3)
    assert story["sound"] == [
        {"cue_id": "paper_unroll", "at_s": round(story["start_s"] + 0.1, 3), "gain_db": 0}
    ]
    assert resolved["seed"] == 7
    assert resolved["theme"] == "night_scrolls"


def test_every_scene_kind_resolves_and_keeps_its_own_fields() -> None:
    authored = load("all_scene_kinds.json")
    files = {"a_garden_dusk": AssetFile(file="library/a_garden_dusk/v1.png")}
    authored["format"]["target_duration_s"] = 22

    resolved = resolve(authored, voice_for(authored), files)

    assert schemas.validate("resolved_spec", resolved) == []
    by_kind = {item["kind"]: item for item in resolved["scenes"]}
    assert by_kind["stat"]["stat"]["claim_id"] == "c_example_habit"
    assert [step["text"] for step in by_kind["steps"]["steps"]] == [
        "Pick one thing",
        "Make it tiny",
        "Do it daily",
    ]
    assert by_kind["scroll"]["title"] == "THE GARDEN"
    assert by_kind["outro"]["hold_s"] == 2
    assert resolved["claims"] == authored["claims"]


def test_resolving_is_repeatable_and_leaves_its_input_alone() -> None:
    authored = load("all_scene_kinds.json")
    authored["format"]["target_duration_s"] = 22
    untouched = copy.deepcopy(authored)
    files = {"a_garden_dusk": AssetFile(file="library/a_garden_dusk/v1.png")}

    first = resolve(authored, voice_for(authored), files)
    second = resolve(authored, voice_for(authored), files)

    assert first == second
    assert authored == untouched
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_times_are_rounded_to_milliseconds() -> None:
    authored = spec([scene("s01", "a b c")], target_duration_s=1.7)
    voice = {"s01": timing("a b c", 1.0, "s01")}

    words = resolve(authored, voice, {})["scenes"][0]["narration"]["words"]

    assert [word["start_s"] for word in words] == [0.3, 0.633, 0.967]


def test_the_resolver_module_lives_in_the_render_package() -> None:
    import packages.render.resolver as module

    assert Path(module.__file__).parent.name == "render"
