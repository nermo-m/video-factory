"""Pronunciation dictionary and passage planning (design doc section 7.4).

A narration passage is cut into pieces before it is turned into phonemes:

* Speak: a run of ordinary words, given to the text-to-phoneme step as it is written.
* Phonemes: a word found in the channel's pronunciation dictionary, already phonemes.
* Mark: punctuation, which the voice model reads as a pause or a tone.

The dictionary matches whole words in any case. An inflected form ("Nermin's") is a
different word and needs its own entry.

This module is pure: no files, no programs, no network.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

# Punctuation the voice model knows.
MARKS = ';:,.!?—…"()“”'
# These split a word even with letters on both sides ("steps—small ones"). The others
# stay inside a word there ("3.5", "10,000", "12:30").
_ALWAYS_SPLIT = "—…"


@dataclass(frozen=True)
class Speak:
    """Ordinary words, to be turned into phonemes."""

    text: str


@dataclass(frozen=True)
class Phonemes:
    """A dictionary word, already in phonemes."""

    value: str


@dataclass(frozen=True)
class Mark:
    """Punctuation. `opens` is true for marks written before a word, like an opening quote."""

    value: str
    opens: bool = False


Piece = Speak | Phonemes | Mark


def plan_passage(text: str, dictionary: Mapping[str, str]) -> list[Piece]:
    """Cut a narration passage into spoken runs, dictionary words and punctuation."""
    known = {word.casefold(): phonemes.strip() for word, phonemes in dictionary.items()}
    pieces: list[Piece] = []
    run: list[str] = []

    def end_run() -> None:
        if run:
            pieces.append(Speak(" ".join(run)))
            run.clear()

    for token in _spaced(text).split():
        word = token.lstrip(MARKS)
        before = token[: len(token) - len(word)]
        word = word.rstrip(MARKS)
        after = token[len(before) + len(word) :]
        if before:
            end_run()
            pieces.append(Mark(before, opens=True))
        if word.casefold() in known:
            end_run()
            pieces.append(Phonemes(known[word.casefold()]))
        elif word:
            run.append(word)
        if after:
            end_run()
            pieces.append(Mark(after))
    end_run()
    return pieces


def join_phonemes(pieces: Sequence[Piece], spoken: Sequence[str]) -> str:
    """Put a passage back together as one phoneme string.

    `spoken` holds the phonemes of each Speak piece, in order. Pieces are separated by one
    space. A mark hugs the word before it, an opening mark the word after it.
    """
    remaining = iter(spoken)
    joined = ""
    glue = ""
    for piece in pieces:
        if isinstance(piece, Mark):
            if piece.opens:
                joined += glue + piece.value
                glue = ""
            else:
                joined += piece.value
                glue = " "
            continue
        value = piece.value if isinstance(piece, Phonemes) else next(remaining)
        value = " ".join(value.split())
        if value:
            joined += glue + value
            glue = " "
    return joined.strip()


def check_dictionary(dictionary: Mapping[str, str], vocabulary: Collection[str]) -> list[str]:
    """Problems in a pronunciation dictionary, in words the owner can act on."""
    problems: list[str] = []
    for word, phonemes in dictionary.items():
        if not word.strip() or len(word.split()) != 1:
            problems.append(f"'{word}': an entry must be a single word.")
            continue
        if not phonemes.strip():
            problems.append(f"'{word}': the phonemes are empty.")
            continue
        unknown = sorted({character for character in phonemes if character not in vocabulary})
        if unknown:
            problems.append(
                f"'{word}': the voice does not know these characters: {' '.join(unknown)}"
            )
    return problems


def _spaced(text: str) -> str:
    """Put spaces around the marks that always separate words."""
    for mark in _ALWAYS_SPLIT:
        text = text.replace(mark, f"{mark} ")
    return text
