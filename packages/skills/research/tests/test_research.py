"""The instructions of the research skill say what the design asks of it (section 6)."""

from __future__ import annotations

import pytest

from packages.skills.planner import load_skill


@pytest.mark.parametrize(
    "phrase",
    [
        "page you retrieved",
        "Never state a claim from memory",
        "empty `claims` list",
        "At most three claims",
    ],
)
def test_the_instructions_ask_for_research_rules(phrase: str) -> None:
    """Only retrieved sources, and an empty answer is allowed."""
    assert phrase in load_skill("research").instructions
