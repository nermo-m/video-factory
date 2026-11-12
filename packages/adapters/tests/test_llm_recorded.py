"""The language model mock: recorded responses for demo mode (design doc 3.3, FR-16)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from packages.adapters.factory import Adapters
from packages.adapters.llm import LLMRequest, RecordedLLM, request_hash
from packages.core.enums import ErrorClass, Provider
from packages.core.queue import InvalidOutputError, JobError, NeedsOwnerError
from packages.core.settings import Settings

SCHEMA = {
    "type": "object",
    "required": ["titles", "lesson"],
    "additionalProperties": False,
    "properties": {
        "titles": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
        "lesson": {"type": "string"},
    },
}
BRIEF = {"titles": ["One", "Two", "Three"], "lesson": "Small unseen habits matter."}


def record(folder: Path, skill: str, output: Any, **more: Any) -> Path:
    path = folder / f"{skill}.json"
    path.write_text(
        json.dumps({"skill": skill, "skill_version": "1.0", "output": output, **more}),
        encoding="utf-8",
    )
    return path


def ask(skill: str = "brief", schema: dict[str, Any] | None = SCHEMA) -> LLMRequest:
    return LLMRequest(skill=skill, skill_version="1.0", prompt="An idea.", output_schema=schema)


def test_fr16_a_recorded_response_is_replayed_for_its_skill(tmp_path: Path) -> None:
    record(tmp_path, "brief", BRIEF, input_tokens=812, output_tokens=96)

    response = RecordedLLM(tmp_path).complete(ask())

    assert response.output == BRIEF
    assert json.loads(response.text) == BRIEF
    assert (response.input_tokens, response.output_tokens) == (812, 96)


def test_fr16_demo_calls_cost_nothing_and_say_so(tmp_path: Path) -> None:
    record(tmp_path, "brief", BRIEF)

    response = RecordedLLM(tmp_path).complete(ask())

    assert response.provider is Provider.DEMO
    assert response.model == "recorded"
    assert response.cost_usd == Decimal("0")
    assert response.searches == 0


def test_the_same_recording_answers_whatever_the_idea_is(tmp_path: Path) -> None:
    # Demo mode tells one story. A reviewer who types another idea still gets a working
    # pipeline, and the interface says that the answers are recorded.
    record(tmp_path, "brief", BRIEF)
    llm = RecordedLLM(tmp_path)
    other = LLMRequest(
        skill="brief", skill_version="1.0", prompt="Something else.", output_schema=SCHEMA
    )

    assert llm.complete(other).output == llm.complete(ask()).output


def test_recorded_sources_come_back_as_retrieved_passages(tmp_path: Path) -> None:
    source = {
        "url": "https://example.org/habits",
        "title": "A study of habits",
        "cited_text": "Seven in ten kept the habit.",
    }
    record(tmp_path, "research", {"claims": []}, sources=[source], searches=2)

    response = RecordedLLM(tmp_path).complete(ask("research", None))

    assert [(item.url, item.title, item.cited_text) for item in response.sources] == [
        (source["url"], source["title"], source["cited_text"])
    ]
    assert response.searches == 2


def test_a_recording_that_no_longer_fits_the_schema_fails_loudly(tmp_path: Path) -> None:
    path = record(tmp_path, "brief", {"titles": ["Only one"], "lesson": "Short."})

    with pytest.raises(InvalidOutputError) as caught:
        RecordedLLM(tmp_path).complete(ask())

    assert path.name in str(caught.value)
    assert "titles" in str(caught.value)


def test_a_recording_made_for_another_version_of_the_skill_is_refused(tmp_path: Path) -> None:
    record(tmp_path, "brief", BRIEF)
    newer = LLMRequest(skill="brief", skill_version="2.0", prompt="An idea.", output_schema=SCHEMA)

    with pytest.raises(InvalidOutputError, match=r"version 1\.0.*2\.0"):
        RecordedLLM(tmp_path).complete(newer)


def test_a_skill_without_a_recording_is_named(tmp_path: Path) -> None:
    with pytest.raises(JobError) as caught:
        RecordedLLM(tmp_path).complete(ask("direct"))

    assert caught.value.error_class is ErrorClass.BUG
    assert "direct.json" in str(caught.value)


@pytest.mark.parametrize("skill", ["../secrets", "a/b", "", "Brief"])
def test_a_skill_name_cannot_point_outside_the_recordings_folder(
    tmp_path: Path, skill: str
) -> None:
    with pytest.raises(JobError, match="skill name"):
        RecordedLLM(tmp_path).complete(ask(skill))


def test_the_same_request_always_has_the_same_hash() -> None:
    first, second = ask(), ask()
    other = LLMRequest(skill="brief", skill_version="1.0", prompt="Another idea.")

    assert request_hash(first) == request_hash(second)
    assert len(request_hash(first)) == 64
    assert request_hash(first) != request_hash(other)


# --- the factory -------------------------------------------------------------------------


def adapters(mode: str, *, confirmed: bool = False) -> Adapters:
    settings = Settings(
        database_url="postgresql+psycopg://vfs:secret@db:5432/vfs", provider_mode=mode
    )
    return Adapters(settings, paid_apis_confirmed=confirmed)


def test_fr16_demo_mode_uses_the_recordings_bundled_with_the_repository() -> None:
    llm = adapters("demo").llm()

    assert isinstance(llm, RecordedLLM)
    assert llm.folder.parts[-2:] == ("samples", "recordings")


def test_fr28_api_mode_without_the_switch_gives_no_language_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "planted value, not a real key")

    with pytest.raises(NeedsOwnerError, match="Use paid APIs"):
        adapters("api", confirmed=False).llm()
