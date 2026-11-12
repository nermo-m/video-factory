"""Recognise a plan usage limit in what a tool printed (design doc section 3.4, FR-29).

Neither tool reports a limit in a form meant for programs, so this reads their sentences.
The wordings come from the program text of Claude Code 2.1.300 and Codex 0.144.1 (ADR 8):

* Claude Code: "You've hit your session limit · resets 3pm (Europe/Sofia)", with "weekly",
  "Opus" and other limit names, and a date in front of the time when the reset is not today.
* Codex: "You've hit your usage limit. ... or try again at 3:15 PM." and, for another day,
  "... try again at Nov 14th, 2026 9:05 AM."

Times are in the clock of this PC, which is the clock the tools print them in. A limit
whose reset time cannot be read is still a limit, with no time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_LIMIT = re.compile(
    r"you[\u2019']ve (?:hit|reached) your [^.\n|·]{0,40}?limit|usage limit reached",
    re.IGNORECASE,
)
_LABEL = re.compile(r"^\s*error:\s*", re.IGNORECASE)
_EPOCH = re.compile(r"\|\s*(\d{9,11})\b")
_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_RELATIVE = re.compile(
    r"(?:try again|resets) in((?:\s+\d+\s*(?:days?|hours?|minutes?|seconds?|[dhms])\b)+)",
    re.IGNORECASE,
)
_PART = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_ABSOLUTE = re.compile(
    r"(?:resets|try again at)\s+(?:at\s+)?"
    r"(?:(?P<month>" + "|".join(_MONTHS) + r")[a-z]*\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?"
    r"(?:,?\s+(?P<year>\d{4}))?(?:,|\s+at)?\s*)?"
    r"(?:(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<half>am|pm)?)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Limit:
    """A usage limit a tool reported: its own sentence, and when it resets if it said so."""

    message: str
    retry_at: datetime | None


def find_limit(text: str, *, now: datetime) -> Limit | None:
    """The usage limit in a tool's error text, or None when the text reports something else.

    `now` must carry the time zone of this PC. Only error text belongs here: an answer
    that merely talks about limits is not a limit.
    """
    found = _LIMIT.search(text)
    if found is None:
        return None
    start = text.rfind("\n", 0, found.start()) + 1
    end = text.find("\n", found.end())
    line = text[start : end if end != -1 else len(text)]
    message = _LABEL.sub("", line).strip()
    return Limit(message=message[:300], retry_at=_reset_time(message, now))


def _reset_time(message: str, now: datetime) -> datetime | None:
    epoch = _EPOCH.search(message)
    if epoch is not None:
        return datetime.fromtimestamp(int(epoch.group(1)), UTC)
    relative = _RELATIVE.search(message)
    if relative is not None:
        seconds = sum(
            int(amount) * _UNITS[unit.lower()] for amount, unit in _PART.findall(relative.group(1))
        )
        return now + timedelta(seconds=seconds)
    absolute = _ABSOLUTE.search(message)
    if absolute is None:
        return None
    try:
        return _absolute_time(absolute, now)
    except ValueError:
        return None


def _absolute_time(found: re.Match[str], now: datetime) -> datetime | None:
    month, hour = found.group("month"), found.group("hour")
    if month is None and hour is None:
        return None
    clock = _clock(hour, found.group("minute"), found.group("half"))
    if month is None:
        today = now.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
        return today if today > now else today + timedelta(days=1)
    number = _MONTHS.index(month.lower()) + 1
    day = int(found.group("day"))
    if found.group("year") is not None:
        return datetime(int(found.group("year")), number, day, *clock, tzinfo=now.tzinfo)
    this_year = datetime(now.year, number, day, *clock, tzinfo=now.tzinfo)
    # A date without a year lies ahead. A day of slack covers a reset that has just passed.
    if this_year < now - timedelta(days=1):
        return datetime(now.year + 1, number, day, *clock, tzinfo=now.tzinfo)
    return this_year


def _clock(hour: str | None, minute: str | None, half: str | None) -> tuple[int, int]:
    if hour is None:
        return (0, 0)
    hours = int(hour)
    if half is not None:
        if not 1 <= hours <= 12:
            raise ValueError(hour)
        hours = hours % 12 + (12 if half.lower() == "pm" else 0)
    return (hours, int(minute) if minute is not None else 0)
