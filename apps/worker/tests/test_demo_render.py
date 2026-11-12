"""`make demo-render`: the sample episode from spec to checked video (FR-16).

The steps before FFmpeg are tested here. The render itself runs in the worker image, in
the test marked `render` at the end of this file.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from apps.worker import demo_render
from packages.adapters.tts.base import Narration, VoiceError
from packages.adapters.tts.samples import SampleVoice


class NoVoice:
    """A voice adapter on a machine with neither the model nor a matching recording."""

    def synthesise(
        self,
        text: str,
        *,
        voice_id: str,
        speed: float = 1.0,
        pronunciation: Mapping[str, str] | None = None,
    ) -> Narration:
        raise VoiceError("There is no bundled sample for this narration. Run: make models")


@pytest.fixture(scope="module")
def authored() -> dict[str, Any]:
    return demo_render.load_sample()


def test_the_sample_is_prepared_with_its_pictures_voice_and_resolved_spec(
    authored: dict[str, Any], tmp_path: Path
) -> None:
    prepared = demo_render.prepare(authored, SampleVoice(demo_render.VOICE_DIR), tmp_path)

    assert prepared.voice_engine == "sample"
    assert prepared.storage == tmp_path / "storage"
    assert [scene["id"] for scene in prepared.resolved["scenes"]] == [
        scene["id"] for scene in authored["scenes"]
    ]
    first = prepared.resolved["scenes"][0]["narration"]
    assert first["audio_file"] == "voice/s01_hook.wav"
    assert len(first["words"]) == len(authored["scenes"][0]["narration"].split())


def test_a_spec_the_theme_cannot_draw_is_refused_before_anything_is_spoken(
    authored: dict[str, Any], tmp_path: Path
) -> None:
    unfit = copy.deepcopy(authored)
    unfit["scenes"][0]["sound"][0]["cue_id"] = "thunder"

    with pytest.raises(demo_render.DemoError, match="thunder"):
        demo_render.prepare(unfit, NoVoice(), tmp_path)

    assert not (tmp_path / "storage" / "voice").exists()


def test_a_missing_voice_ends_the_command_with_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(demo_render, "create_tts_adapter", lambda *paths, **options: NoVoice())

    code = demo_render.main(["--out", str(tmp_path / "demo")])

    assert code == 1
    said = capsys.readouterr().err
    assert "The demo could not be rendered" in said
    assert "make models" in said


@pytest.mark.render
def test_fr16_the_demo_renders_from_bundled_files_and_passes_the_format_checks(
    tmp_path: Path,
) -> None:
    result = demo_render.render_demo(
        tmp_path, tts=SampleVoice(demo_render.VOICE_DIR), preview=True, workers=3
    )

    assert result.problems == []
    assert result.voice_engine == "sample"
    assert result.duration_s == pytest.approx(45.0, abs=2.0)
    assert result.video.is_file()
    assert result.contact_sheet.is_file()
    assert (tmp_path / "resolved_spec.json").is_file()


@pytest.mark.render
def test_the_command_prints_where_the_video_is_and_that_the_checks_passed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        demo_render,
        "create_tts_adapter",
        lambda *paths, **options: SampleVoice(demo_render.VOICE_DIR),
    )

    code = demo_render.main(["--out", str(tmp_path), "--preview", "--workers", "3"])

    said = capsys.readouterr().out
    assert code == 0
    assert "preview.mp4" in said
    assert "from the bundled recordings" in said
    assert "Format checks:  passed" in said
