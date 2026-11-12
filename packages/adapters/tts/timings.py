"""Word timing estimate for narration (design doc section 7.3).

Kokoro returns audio and nothing else. Word times are estimated: each sentence's audio
time is shared between its words by letter count, with extra weight for the pause after
punctuation. Where a sentence starts and ends comes from the pauses measured in the audio.

Three attempts, the most exact first:

1. Every punctuation mark is matched to a measured pause, so each phrase gets its own
   stretch of audio.
2. Only the sentence ends are matched, and commas get their share by weight.
3. Nothing is matched, and the whole passage is shared by weight.

An attempt is dropped when the audio has too few pauses for it, or when it would make
one part of the narration implausibly fast or slow.

A forced-alignment step may replace this later. It must return the same list of
WordTiming, one per whitespace-separated word, so nothing else changes.

This module is pure: no files, no audio library, no clock.
"""

from __future__ import annotations

from collections.abc import Sequence

from packages.render.resolver import WordTiming

SENTENCE_MARKS = ".!?…"
CLAUSE_MARKS = ",;:—–"
# How long the pause after a mark is, counted in letters of speech.
SENTENCE_PAUSE_LETTERS = 5.0
CLAUSE_PAUSE_LETTERS = 2.0
# A silence this close to either end of the audio is the lead-in or the tail.
EDGE_S = 0.02
# A phrase or sentence spoken this many times faster or slower than the passage as a whole
# means the pauses were matched to the wrong places.
MAX_RATE_RATIO = 2.5
_CLOSING = "\"'”’)]"

Span = tuple[float, float]


def estimate_word_timings(
    text: str, duration_s: float, silences: Sequence[Span] = ()
) -> list[WordTiming]:
    """Estimate when each word of a narration is spoken.

    `silences` are the quiet stretches measured in the audio, as (start, end) in seconds.
    Returns one timing per whitespace-separated word, in order, as the word is written.
    """
    if duration_s <= 0:
        raise ValueError("The audio duration must be more than zero seconds.")
    words = text.split()
    if not words:
        return []

    speech, pauses = _speech_and_pauses(duration_s, silences)
    for weight in (CLAUSE_PAUSE_LETTERS, SENTENCE_PAUSE_LETTERS):
        groups = _groups(words, weight)
        spans = _spans(groups, speech, pauses)
        if spans is not None:
            return [
                timing
                for group, (start, end) in zip(groups, spans, strict=True)
                for timing in _share(group, start, end)
            ]
    return _share(words, *speech)


def _letters(word: str) -> float:
    """The weight of a word: its letters and digits, at least one."""
    return float(max(1, sum(character.isalnum() for character in word)))


def _pause_after(word: str) -> float:
    """The weight of the pause that follows a word, from the mark it ends with."""
    bare = word.rstrip(_CLOSING)
    if not bare:
        return 0.0
    if bare[-1] in SENTENCE_MARKS:
        return SENTENCE_PAUSE_LETTERS
    if bare[-1] in CLAUSE_MARKS:
        return CLAUSE_PAUSE_LETTERS
    return 0.0


def _groups(words: Sequence[str], smallest_pause: float) -> list[list[str]]:
    """Words grouped up to each mark whose pause is at least this heavy.

    With the clause weight a group is a phrase, with the sentence weight a sentence.
    """
    groups: list[list[str]] = [[]]
    for word in words:
        groups[-1].append(word)
        if _pause_after(word) >= smallest_pause:
            groups.append([])
    return [group for group in groups if group]


def _speech_and_pauses(duration_s: float, silences: Sequence[Span]) -> tuple[Span, list[Span]]:
    """Where the speech starts and ends, and the pauses inside it."""
    start, end = 0.0, duration_s
    inner: list[Span] = []
    for silence_start, silence_end in sorted(silences):
        if silence_start <= EDGE_S:
            start = max(start, min(silence_end, duration_s))
        elif silence_end >= duration_s - EDGE_S:
            end = min(end, silence_start)
        else:
            inner.append((silence_start, silence_end))
    if end <= start:
        return (0.0, duration_s), []
    return (start, end), [pause for pause in inner if start < pause[0] and pause[1] < end]


def _spans(
    groups: Sequence[Sequence[str]], speech: Span, pauses: Sequence[Span]
) -> list[Span] | None:
    """The stretch of audio each group is spoken in, or None when it cannot be told.

    The breaks between groups are taken to be the longest pauses in the audio.
    """
    breaks = len(groups) - 1
    if breaks == 0:
        return [speech]
    if len(pauses) < breaks:
        return None
    longest = sorted(sorted(pauses, key=lambda pause: pause[0] - pause[1])[:breaks])
    edges = [speech[0], *(edge for pause in longest for edge in pause), speech[1]]
    spans = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]

    weights = [sum(_letters(word) for word in group) for group in groups]
    spoken = sum(end - start for start, end in spans)
    overall = sum(weights) / spoken
    for weight, (start, end) in zip(weights, spans, strict=True):
        rate = weight / (end - start)
        if not overall / MAX_RATE_RATIO <= rate <= overall * MAX_RATE_RATIO:
            return None
    return spans


def _share(words: Sequence[str], start_s: float, end_s: float) -> list[WordTiming]:
    """Share a stretch of audio between words by letter count, with pauses after marks."""
    pauses = [_pause_after(word) for word in words[:-1]] + [0.0]
    total = sum(_letters(word) for word in words) + sum(pauses)
    per_letter = (end_s - start_s) / total
    timings: list[WordTiming] = []
    units = 0.0
    for word, pause in zip(words, pauses, strict=True):
        word_start = start_s + units * per_letter
        units += _letters(word)
        timings.append(WordTiming(word, word_start, start_s + units * per_letter))
        units += pause
    return timings
