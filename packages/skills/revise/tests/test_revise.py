"""The instructions of the revise skill say what the design asks of it (section 6)."""

from __future__ import annotations

import pytest

from packages.skills.planner import load_skill


@pytest.mark.parametrize(
    "phrase",
    [
        "JSON Patch",
        "smallest patch",
        "Never change `spec_version`",
        "summary",
    ],
)
def test_the_instructions_ask_for_revise_rules(phrase: str) -> None:
    """A minimal patch."""
    assert phrase in load_skill("revise").instructions
