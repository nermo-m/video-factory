"""The instructions of the assets skill say what the design asks of it (section 6)."""

from __future__ import annotations

import pytest

from packages.skills.planner import load_skill


@pytest.mark.parametrize(
    "phrase",
    [
        "style_block`, word for word",
        "no text inside the picture",
        "belong to someone",
        "used_in",
    ],
)
def test_the_instructions_ask_for_assets_rules(phrase: str) -> None:
    """The style block and no third-party content."""
    assert phrase in load_skill("assets").instructions
