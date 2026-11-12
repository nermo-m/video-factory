"""Usage limit messages of the two tools (design doc section 3.4, FR-29).

"A usage limit reported by a tool becomes the error class plan_limit, with the reset time
when the tool gives one." The wordings below are the ones found in the program text of
Claude Code 2.1.300 and Codex 0.144.1 (ADR 8), plus older ones that cost nothing to keep.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tools.cli_bridge.limits import find_limit
from tools.cli_bridge.tests.support import NOW, ZONE


def at(month: int, day: int, hour: int, minute: int = 0, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZONE)


@pytest.mark.parametrize(
    ("message", "resets"),
    [
        ("You've hit your session limit · resets 3pm (Europe/Sofia)", at(11, 12, 15)),
        ("You've hit your session limit · resets 3:30pm", at(11, 12, 15, 30)),
        ("You've hit your session limit · resets 3 PM · progress saved", at(11, 12, 15)),
        ("You've hit your weekly limit · resets Nov 14, 9am (Europe/Sofia)", at(11, 14, 9)),
        ("You've hit your weekly limit · resets Nov 14 at 9:15am", at(11, 14, 9, 15)),
        ("You've hit your Opus limit · resets Nov 19, 12am", at(11, 19, 0)),
        ("You\u2019ve hit your session limit · resets 12pm", at(11, 13, 12)),
    ],
)
def test_fr29_a_claude_limit_gives_its_reset_time(message: str, resets: datetime) -> None:
    limit = find_limit(message, now=NOW)

    assert limit is not None
    assert limit.retry_at == resets


def test_fr29_a_time_that_has_passed_today_means_tomorrow() -> None:
    limit = find_limit("You've hit your session limit · resets 9am", now=NOW)

    assert limit is not None
    assert limit.retry_at == at(11, 13, 9)


def test_fr29_a_date_without_a_year_is_the_next_such_date() -> None:
    new_years_eve = datetime(2026, 12, 30, 22, 0, tzinfo=ZONE)

    limit = find_limit("You've hit your weekly limit · resets Jan 2, 9am", now=new_years_eve)

    assert limit is not None
    assert limit.retry_at == at(1, 2, 9, year=2027)


def test_fr29_the_older_claude_message_carries_the_time_as_a_number() -> None:
    limit = find_limit("Claude AI usage limit reached|1763125200", now=NOW)

    assert limit is not None
    assert limit.retry_at == datetime.fromtimestamp(1763125200, UTC)


@pytest.mark.parametrize(
    ("message", "resets"),
    [
        (
            "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
            "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try "
            "again at 3:15 PM.",
            at(11, 12, 15, 15),
        ),
        (
            "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to "
            "purchase more credits or try again at Nov 14th, 2026 9:05 AM.",
            at(11, 14, 9, 5),
        ),
        (
            "You've hit your usage limit. Try again in 2 days 3 hours 5 minutes.",
            at(11, 14, 16, 5),
        ),
        ("You've hit your usage limit. Try again in 45 minutes.", at(11, 12, 13, 45)),
    ],
)
def test_fr29_a_codex_limit_gives_its_reset_time(message: str, resets: datetime) -> None:
    limit = find_limit(message, now=NOW)

    assert limit is not None
    assert limit.retry_at == resets


@pytest.mark.parametrize(
    "message",
    [
        "You've hit your usage limit. To get more access now, send a request to your admin "
        "or try again later.",
        "You've hit your monthly spend limit.",
        "Usage limit reached. You've reached your usage limit. Increase your limits to "
        "continue using codex.",
        "You've hit your session limit",
    ],
)
def test_fr29_a_limit_without_a_reset_time_is_still_a_limit(message: str) -> None:
    limit = find_limit(message, now=NOW)

    assert limit is not None
    assert limit.retry_at is None


@pytest.mark.parametrize(
    "message",
    [
        "",
        "API Error: 529 Overloaded. Server is temporarily limiting requests (not your usage limit)",
        "Rate limit reached for requests. Please try again in 1.898s.",
        "stream disconnected before completion: error sending request",
        "Context limit reached · /compact or /clear to continue",
        "Reached maximum number of turns (4)",
    ],
)
def test_other_failures_are_not_taken_for_a_plan_limit(message: str) -> None:
    assert find_limit(message, now=NOW) is None


def test_the_limit_keeps_the_tools_own_words_for_the_owner() -> None:
    limit = find_limit(
        "Error: You've hit your session limit · resets 3pm (Europe/Sofia)\n", now=NOW
    )

    assert limit is not None
    assert limit.message == "You've hit your session limit · resets 3pm (Europe/Sofia)"
