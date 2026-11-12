"""Text to phonemes through the espeak-ng program, in the alphabet the Kokoro model reads."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from packages.adapters.tts.base import VoiceError
from packages.adapters.tts.espeak import espeak_phonemes, to_kokoro


class FakeProgram:
    """Stands in for subprocess.run and remembers how it was called."""

    def __init__(self, stdout: str = "", error: Exception | None = None) -> None:
        self.stdout = stdout
        self.error = error
        self.calls: list[list[str]] = []
        self.options: dict[str, Any] = {}

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        self.options = options
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(command, 0, stdout=self.stdout, stderr="")


@pytest.mark.parametrize(
    ("ipa", "british", "expected"),
    [
        # Two-letter sounds become the model's single letters.
        ("klˈa^ɪmd", True, "klˈImd"),
        ("sˈe^ɪm", True, "sˈAm"),
        ("kˈa^ʊnt", False, "kˈWnt"),
        ("t^ʃˈɔ^ɪs", False, "ʧˈYs"),
        ("d^ʒˈʌd^ʒ", False, "ʤˈʌʤ"),
        # British and American differ in how "oh" is written.
        ("nˈə^ʊbɒdi", True, "nˈQbɒdi"),
        ("ˈo^ʊpən", False, "ˈOpən"),
        # American drops the length mark, British keeps it.
        ("kˈiːps", False, "kˈips"),
        ("kˈiːpə", True, "kˈiːpə"),
        ("ɹˈɛd", False, "ɹˈɛd"),
    ],
)
def test_espeak_phonemes_are_rewritten_for_the_model(
    ipa: str, british: bool, expected: str
) -> None:
    assert to_kokoro(ipa, british=british) == expected


def test_the_program_is_asked_for_ipa_in_the_right_accent() -> None:
    program = FakeProgram(stdout=" smˈɔːl stˈɛps\n")

    espeak_phonemes("Small steps", british=True, run=program)
    espeak_phonemes("Small steps", british=False, run=program)

    assert program.calls[0][0] == "espeak-ng"
    assert program.calls[0][program.calls[0].index("-v") + 1] == "en-gb"
    assert program.calls[1][program.calls[1].index("-v") + 1] == "en-us"
    assert "--ipa" in program.calls[0]


def test_the_text_cannot_be_read_as_an_option() -> None:
    program = FakeProgram(stdout="x\n")

    espeak_phonemes("--version", british=False, run=program)

    command = program.calls[0]
    assert command[-2:] == ["--", "--version"]
    # Never through a shell, so nothing in the narration can run a command.
    assert program.options.get("shell", False) is False


def test_several_output_lines_become_one_phoneme_string() -> None:
    program = FakeProgram(stdout=" hiː klˈa^ɪmd\n ˈɛnɪwˌe^ɪ\n")

    assert espeak_phonemes("He climbed anyway", british=True, run=program) == "hiː klˈImd ˈɛnɪwˌA"


def test_a_missing_program_says_where_it_lives() -> None:
    program = FakeProgram(error=FileNotFoundError("espeak-ng"))

    with pytest.raises(VoiceError, match="espeak-ng is not installed") as caught:
        espeak_phonemes("Small steps", british=False, run=program)

    assert "worker image" in str(caught.value)


def test_a_failing_or_hanging_program_is_a_voice_error() -> None:
    failing = FakeProgram(error=subprocess.CalledProcessError(1, "espeak-ng", stderr="bad voice"))
    hanging = FakeProgram(error=subprocess.TimeoutExpired("espeak-ng", 10))

    with pytest.raises(VoiceError, match="bad voice"):
        espeak_phonemes("Small steps", british=False, run=failing)
    with pytest.raises(VoiceError, match="did not answer"):
        espeak_phonemes("Small steps", british=False, run=hanging)
