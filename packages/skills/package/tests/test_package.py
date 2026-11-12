"""The instructions of the package skill say what the design asks of it (section 6)."""

from __future__ import annotations

import pytest

from packages.skills.planner import load_skill


@pytest.mark.parametrize(
    "phrase",
    [
        "at most 100 characters",
        "cover_frame_s",
        "hashtags",
    ],
)
def test_the_instructions_ask_for_package_rules(phrase: str) -> None:
    """A package for manual upload."""
    assert phrase in load_skill("package").instructions
