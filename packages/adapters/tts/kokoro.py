"""The Kokoro voice: local, English, no key and no GPU (design doc sections 3.3 and 7).

The model file is run with ONNX Runtime. Text becomes phonemes through the espeak-ng
program (see espeak.py), with the channel's pronunciation dictionary applied first. One
scene is one passage and one run of the model, because sentence-by-sentence clips sound
choppy (section 7.4). The model returns audio only, so word timings are estimated
(section 7.3).

Checked against the model file that `make models` downloads (kokoro-v1.0.onnx): inputs
`tokens` (int64, padded with a zero at each end), `style` (one row of the voice, chosen by
the number of tokens) and `speed`. Output: audio at 24 kHz. At most 510 tokens per run.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import onnxruntime
from numpy.typing import NDArray

from packages.adapters.tts.audio import find_silences, to_wav
from packages.adapters.tts.base import Narration, VoiceError
from packages.adapters.tts.espeak import espeak_phonemes
from packages.adapters.tts.pronunciation import Speak, check_dictionary, join_phonemes, plan_passage
from packages.adapters.tts.timings import estimate_word_timings

SAMPLE_RATE = 24000
MAX_TOKENS = 510
MIN_SPEED, MAX_SPEED = 0.5, 2.0
# Voice names start with the accent and the gender: af_, am_ (American), bf_, bm_ (British).
_ENGLISH_VOICE = re.compile(r"[ab][fm]_\w+")
_VOCABULARY_FILE = Path(__file__).with_name("kokoro_vocab.json")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class ModelSession(Protocol):
    def run(self, output_names: Any, inputs: dict[str, NDArray[Any]]) -> Sequence[Any]:
        """Run the model once, like onnxruntime.InferenceSession.run."""


class Phonemiser(Protocol):
    def __call__(self, text: str, *, british: bool) -> str:
        """Turn a run of ordinary words into phonemes."""


def load_vocabulary() -> dict[str, int]:
    """The model's phoneme characters and their token numbers."""
    vocabulary: dict[str, int] = json.loads(_VOCABULARY_FILE.read_text(encoding="utf-8"))["vocab"]
    return vocabulary


class KokoroVoice:
    """TTSAdapter backed by the Kokoro model. The model is loaded on first use."""

    def __init__(
        self,
        model_path: Path,
        voices_path: Path,
        *,
        phonemise: Phonemiser = espeak_phonemes,
        session: ModelSession | None = None,
        voices: Mapping[str, NDArray[np.float32]] | None = None,
    ) -> None:
        self.model_path = model_path
        self.voices_path = voices_path
        self._phonemise = phonemise
        self._session = session
        self._voices = voices
        self._vocabulary = load_vocabulary()

    def synthesise(
        self,
        text: str,
        *,
        voice_id: str,
        speed: float = 1.0,
        pronunciation: Mapping[str, str] | None = None,
    ) -> Narration:
        if not text.strip():
            raise VoiceError("There is no narration to speak.")
        if not MIN_SPEED <= speed <= MAX_SPEED:
            raise VoiceError(
                f"The voice speed must be between {MIN_SPEED} and {MAX_SPEED}, not {speed}."
            )
        dictionary = dict(pronunciation or {})
        problems = check_dictionary(dictionary, self._vocabulary)
        if problems:
            raise VoiceError("The pronunciation dictionary has problems:\n" + "\n".join(problems))

        session, voices = self._load()
        style_rows = self._voice(voices, voice_id)
        phonemes = self._phonemes(text, dictionary, british=voice_id.startswith("b"))
        if not phonemes:
            raise VoiceError(f"The narration has nothing the voice can say: {text!r}")

        parts = [
            self._run(session, style_rows, batch, speed)
            for batch in split_batches(phonemes, MAX_TOKENS)
        ]
        samples = np.concatenate(parts).astype(np.float32)
        duration_s = len(samples) / SAMPLE_RATE
        return Narration(
            wav=to_wav(samples, SAMPLE_RATE),
            sample_rate=SAMPLE_RATE,
            duration_s=duration_s,
            words=estimate_word_timings(text, duration_s, find_silences(samples, SAMPLE_RATE)),
            engine="kokoro",
        )

    # --- steps -----------------------------------------------------------------------

    def _load(self) -> tuple[ModelSession, Mapping[str, NDArray[np.float32]]]:
        if self._session is not None and self._voices is not None:
            return self._session, self._voices
        missing = [path for path in (self.model_path, self.voices_path) if not path.is_file()]
        if missing:
            raise VoiceError(
                "The voice model files are missing: "
                + ", ".join(str(path) for path in missing)
                + ". Download them with: make models"
            )
        try:
            if self._session is None:
                self._session = onnxruntime.InferenceSession(
                    str(self.model_path), providers=["CPUExecutionProvider"]
                )
            if self._voices is None:
                # A NumPy archive of plain arrays. Pickled objects are refused.
                self._voices = np.load(self.voices_path, allow_pickle=False)
        except Exception as error:
            # ONNX Runtime raises its own exception types for a damaged or foreign file.
            raise VoiceError(
                f"The voice model files could not be loaded ({error}). "
                "Delete them and download them again with: make models"
            ) from error
        return self._session, self._voices

    def _voice(
        self, voices: Mapping[str, NDArray[np.float32]], voice_id: str
    ) -> NDArray[np.float32]:
        if not _ENGLISH_VOICE.fullmatch(voice_id):
            raise VoiceError(
                f"'{voice_id}' is not an English voice. Only English voices are supported: "
                "names that start with af_, am_, bf_ or bm_."
            )
        if voice_id not in voices:
            english = sorted(name for name in voices if _ENGLISH_VOICE.fullmatch(name))
            raise VoiceError(
                f"There is no voice '{voice_id}'. Available voices: {', '.join(english)}."
            )
        return voices[voice_id]

    def _phonemes(self, text: str, dictionary: Mapping[str, str], *, british: bool) -> str:
        pieces = plan_passage(text, dictionary)
        spoken = [
            self._phonemise(piece.text, british=british)
            for piece in pieces
            if isinstance(piece, Speak)
        ]
        joined = join_phonemes(pieces, spoken)
        known = "".join(character for character in joined if character in self._vocabulary)
        return " ".join(known.split())

    def _run(
        self,
        session: ModelSession,
        style_rows: NDArray[np.float32],
        phonemes: str,
        speed: float,
    ) -> NDArray[np.float32]:
        tokens = [self._vocabulary[character] for character in phonemes]
        style = style_rows[min(len(tokens), len(style_rows)) - 1]
        outputs = session.run(
            None,
            {
                "tokens": np.array([[0, *tokens, 0]], dtype=np.int64),
                "style": np.asarray(style, dtype=np.float32).reshape(1, -1),
                "speed": np.array([speed], dtype=np.float32),
            },
        )
        audio: NDArray[np.float32] = np.asarray(outputs[0], dtype=np.float32).ravel()
        return audio


def split_batches(phonemes: str, limit: int) -> list[str]:
    """Cut a phoneme string into parts the model can take in one run.

    A scene's narration nearly always fits in one part. A longer one is cut at sentence
    ends, and a single sentence that is still too long at spaces.
    """
    if len(phonemes) <= limit:
        return [phonemes]
    batches: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(phonemes):
        for piece in _fit(sentence, limit):
            candidate = f"{current} {piece}" if current else piece
            if len(candidate) <= limit:
                current = candidate
            else:
                batches.append(current)
                current = piece
    if current:
        batches.append(current)
    return batches


def _fit(sentence: str, limit: int) -> list[str]:
    """One sentence as pieces of at most `limit` characters, cut at spaces when needed."""
    if len(sentence) <= limit:
        return [sentence]
    pieces: list[str] = []
    current = ""
    for word in sentence.split(" "):
        while len(word) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:limit])
            word = word[limit:]
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= limit:
            current = candidate
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces
