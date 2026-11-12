"""The instructions of the brief skill say what the design asks of it (section 6)."""

from __future__ import annotations

import pytest

from packages.skills.planner import load_skill


@pytest.mark.parametrize(
    "phrase",
    [
        "exactly three",
        "Invent no facts",
        "past_titles",
        "belong to someone else",
    ],
)
def test_the_instructions_ask_for_brief_rules(phrase: str) -> None:
    """Three title options and no invented facts."""
    assert phrase in load_skill("brief").instructions
