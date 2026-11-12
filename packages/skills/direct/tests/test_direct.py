"""The instructions of the direct skill say what the design asks of it (section 6)."""

from __future__ import annotations

import pytest

from packages.skills.planner import load_skill


@pytest.mark.parametrize(
    "phrase",
    [
        "You do not rewrite them",
        "Use only what `capabilities` lists",
        "retention_device",
        "every three seconds",
        "Words are counted from zero",
    ],
)
def test_the_instructions_ask_for_direct_rules(phrase: str) -> None:
    """Only the theme's capabilities and the script's own words."""
    assert phrase in load_skill("direct").instructions
