"""Estimated lengths of a plan before the voice exists (design doc sections 5.2 and 11.2)."""

from __future__ import annotations

import pytest

from packages.core import lengths


def test_a_scene_takes_its_words_at_speaking_pace_plus_the_pause_around_it() -> None:
    narration = " ".join(["word"] * 23)

    assert lengths.scene_seconds(narration) == pytest.approx(10 + lengths.PAUSE_PER_SCENE_S)


def test_a_faster_voice_makes_a_scene_shorter() -> None:
    narration = " ".join(["word"] * 23)

    assert lengths.scene_seconds(narration, speed=1.25) == pytest.approx(
        8 + lengths.PAUSE_PER_SCENE_S
    )


def test_a_scene_without_narration_is_only_its_pause() -> None:
    assert lengths.scene_seconds("") == pytest.approx(lengths.PAUSE_PER_SCENE_S)
    assert lengths.scene_seconds("   ") == pytest.approx(lengths.PAUSE_PER_SCENE_S)


def test_the_accepted_range_is_the_tolerance_widened_by_the_estimates_slack() -> None:
    low, high = lengths.accepted_range(45)

    assert high == pytest.approx(47 * 1.05)
    assert low == pytest.approx(43 / 1.05)


@pytest.mark.parametrize(
    ("seconds", "fits"),
    [(45.0, True), (49.3, True), (49.4, False), (41.0, True), (40.9, False)],
)
def test_a_plan_fits_when_its_estimate_is_inside_the_accepted_range(
    seconds: float, fits: bool
) -> None:
    assert lengths.fits(seconds, 45) is fits


def test_the_script_budget_and_the_estimate_agree() -> None:
    """A script exactly at its word budget is estimated inside the tolerance."""
    from packages.skills import rules

    budget = rules.word_budget(45, 7)
    per_scene = [budget // 7 + (1 if index < budget % 7 else 0) for index in range(7)]
    total = sum(lengths.scene_seconds(" ".join(["w"] * words)) for words in per_scene)

    assert total <= 45 + lengths.TOLERANCE_S


def test_a_silent_scene_takes_the_length_it_declares() -> None:
    assert lengths.estimate({"narration": "", "duration_s": 0.6}) == pytest.approx(0.6)


def test_a_hold_after_the_narration_is_added() -> None:
    spoken = lengths.scene_seconds("Small steps still count.")

    assert lengths.estimate({"narration": "Small steps still count.", "hold_s": 2}) == (
        pytest.approx(spoken + 2)
    )
    assert lengths.estimate({"narration": "Small steps still count."}) == pytest.approx(spoken)
