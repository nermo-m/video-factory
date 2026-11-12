"""The instructions of the script skill say what the design asks of it (section 6)."""

from __future__ import annotations

import pytest

from packages.skills.planner import load_skill


@pytest.mark.parametrize(
    "phrase",
    [
        "hook",
        "takeaway",
        "word budget is strict",
        "2.3 words per second",
        "One idea per sentence",
    ],
)
def test_the_instructions_ask_for_script_rules(phrase: str) -> None:
    """The structure and the strict word budget."""
    assert phrase in load_skill("script").instructions
