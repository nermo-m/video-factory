"""Text to phonemes with the espeak-ng program, in the alphabet the Kokoro model reads.

espeak-ng is licensed GPL-3.0. It is installed in the worker image as a separate program
and started as one for each piece of text, the same arrangement as FFmpeg. It is never
imported or linked, and no GPL package is a dependency of this project (decision D-021).

espeak-ng writes the International Phonetic Alphabet. The Kokoro model was trained on a
close relative of it in which every sound is one character ("A" for the vowel of "same",
"ʧ" for "ch"). The rewriting below follows the mapping published with the model's own
phoneme library (misaki, Apache-2.0).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

from packages.adapters.tts.base import VoiceError

PROGRAM = "espeak-ng"
TIMEOUT_S = 20
# espeak-ng joins the letters of a two-letter sound with this character when asked to.
_TIE = "^"
_SYLLABIC = "\u0329"  # the combining mark under a syllabic consonant

_BRITISH_FIRST = (("e^ə", "ɛː"), ("ə^ʊ", "Q"))
_AMERICAN_FIRST = (("o^ʊ", "O"),)
_SHARED = (
    ("ʔˌn" + _SYLLABIC, "ʔn"),
    ("ʔn" + _SYLLABIC, "ʔn"),
    ("a^ɪ", "I"),
    ("a^ʊ", "W"),
    ("e^ɪ", "A"),
    ("ɔ^ɪ", "Y"),
    ("d^ʒ", "ʤ"),
    ("t^ʃ", "ʧ"),
    ("ə^l", "ᵊl"),
    ("ʲo", "jo"),
    ("ʲə", "jə"),
    ("ʲ", ""),
    ("ɚ", "əɹ"),
    ("r", "ɹ"),
    ("x", "k"),
    ("ç", "k"),
    ("ɐ", "ə"),
    ("ɬ", "l"),
    ("\u0303", ""),
)
_BRITISH_LAST = (("iə", "ɪə"),)
_AMERICAN_LAST = (("ɜːɹ", "ɜɹ"), ("ɜː", "ɜɹ"), ("ɪə", "iə"), ("ː", ""))
# espeak-ng 1.51 writes a plain "o" where the model expects "ɔ". The flap and the glottal
# stop are written the way the model's version 1.0 voices know them.
_FINAL = (("o", "ɔ"), ("ɾ", "T"), ("ʔ", "t"), (_TIE, ""))


# Runs a program and returns what it wrote, like subprocess.run.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def to_kokoro(ipa: str, *, british: bool) -> str:
    """Rewrite espeak-ng phonemes (with tie characters) in the Kokoro model's alphabet."""
    steps = (
        *(_BRITISH_FIRST if british else _AMERICAN_FIRST),
        *_SHARED,
        *(_BRITISH_LAST if british else _AMERICAN_LAST),
    )
    for old, new in steps:
        ipa = ipa.replace(old, new)
    # A syllabic consonant ("button") is written as a small schwa before the consonant.
    ipa = re.sub(rf"(\S){_SYLLABIC}", r"ᵊ\1", ipa).replace(_SYLLABIC, "")
    for old, new in _FINAL:
        ipa = ipa.replace(old, new)
    return ipa


def espeak_phonemes(text: str, *, british: bool, run: Runner = subprocess.run) -> str:
    """Phonemes for a run of words, in the Kokoro alphabet. Raises VoiceError on failure."""
    command = [
        PROGRAM,
        "-q",
        "--ipa",
        f"--tie={_TIE}",
        "-v",
        "en-gb" if british else "en-us",
        # Everything after "--" is text, so narration can never be read as an option.
        "--",
        text,
    ]
    try:
        # A fixed program name and an argument list, no shell: the narration is data.
        finished = run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=TIMEOUT_S,
        )
    except FileNotFoundError as error:
        raise VoiceError(
            "espeak-ng is not installed. It is part of the worker image: run the voice "
            "inside the worker container, or install espeak-ng on this machine."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise VoiceError(f"espeak-ng did not answer within {TIMEOUT_S} seconds.") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip() or f"exit code {error.returncode}"
        raise VoiceError(f"espeak-ng could not read the narration: {detail}") from error
    return to_kokoro(" ".join(finished.stdout.split()), british=british)
