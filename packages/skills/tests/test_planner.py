"""The planner service and the rules of the skills (design doc sections 4.4 and 6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from packages.adapters.llm import LLMRequest, LLMResponse, RecordedLLM, Source
from packages.core import schemas
from packages.core.enums import ErrorClass, Provider
from packages.core.queue import InvalidOutputError, JobError
from packages.skills import rules
from packages.skills.planner import SKILL_NAMES, SKILLS_DIR, load_skill, run_skill

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = ROOT / "samples" / "recordings"


def example(skill: str, part: str) -> dict[str, Any]:
    path = SKILLS_DIR / skill / "examples" / f"lighthouse_keeper.{part}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def answer(output: Any, *, sources: tuple[Source, ...] = ()) -> LLMResponse:
    return LLMResponse(
        output=output,
        text=json.dumps(output),
        provider=Provider.DEMO,
        model="fake",
        input_tokens=10,
        output_tokens=5,
        cost_usd=Decimal("0"),
        latency_ms=1,
        sources=sources,
    )


class FakeLLM:
    """Answers with what the test lined up, and keeps the requests."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        given = self.answers.pop(0)
        if isinstance(given, Exception):
            raise given
        return given if isinstance(given, LLMResponse) else answer(given)


BRIEF = example("brief", "output")


# --- Skill folders ----------------------------------------------------------------------


# The version of each skill's instructions. A changed instruction is a new version.
VERSIONS = {
    **dict.fromkeys(SKILL_NAMES, "1.0"),
    "brief": "1.1",
    "script": "1.1",
    "direct": "1.2",
    "assets": "1.1",
}


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_every_skill_folder_is_complete(name: str) -> None:
    folder = SKILLS_DIR / name

    for part in ("SKILL.md", "input.schema.json", "output.schema.json", "examples", "tests"):
        assert (folder / part).exists(), f"{name}/{part} is missing"
    skill = load_skill(name)
    assert skill.name == name
    assert skill.version == VERSIONS[name]
    assert len(skill.instructions) > 400
    assert "JSON document" in skill.instructions


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_every_skills_example_fits_its_own_schemas(name: str) -> None:
    skill = load_skill(name)
    llm = FakeLLM(example(name, "output"))

    result = run_skill(llm, skill, example(name, "input"))

    assert result.output == example(name, "output")
    assert (result.skill, result.skill_version, len(result.calls)) == (name, VERSIONS[name], 1)


def test_the_shared_schemas_are_the_skills_output_schemas() -> None:
    shared = {name: load_skill(name).shared_output for name in SKILL_NAMES}

    assert shared == {
        "brief": "brief",
        "research": "claims",
        "script": None,
        "direct": "episode_spec",
        "assets": "asset_manifest",
        "package": "package",
        "revise": None,
    }
    assert load_skill("brief").output_schema == schemas.bundled_schema("brief")


def test_only_research_searches_the_web() -> None:
    assert [name for name in SKILL_NAMES if load_skill(name).web_search] == ["research"]


def test_an_unknown_skill_is_refused() -> None:
    with pytest.raises(ValueError, match="no skill named"):
        load_skill("../../etc")


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_fr16_demo_mode_has_a_recording_for_every_skill(name: str) -> None:
    skill = load_skill(name)

    result = run_skill(RecordedLLM(RECORDINGS), skill, example(name, "input"))

    assert result.output == example(name, "output")


def test_the_recorded_script_is_the_sample_episodes_narration() -> None:
    spec = json.loads(
        (ROOT / "samples" / "lighthouse_keeper" / "episode_spec.json").read_text(encoding="utf-8")
    )
    recorded = json.loads((RECORDINGS / "script.json").read_text(encoding="utf-8"))["output"]

    assert [(scene["id"], scene["narration"]) for scene in recorded["scenes"]] == [
        (scene["id"], scene["narration"]) for scene in spec["scenes"]
    ]


# --- One skill call ---------------------------------------------------------------------


def test_a_skill_call_sends_the_instructions_the_input_and_the_schema() -> None:
    skill = load_skill("brief")
    llm = FakeLLM(BRIEF)

    run_skill(llm, skill, example("brief", "input"))

    (request,) = llm.requests
    assert (request.skill, request.skill_version) == ("brief", "1.1")
    assert request.system == skill.instructions
    assert "A lighthouse keeper who does one small thing" in request.prompt
    assert request.output_schema == skill.output_schema
    assert request.web_search is False


def test_an_input_that_does_not_fit_is_a_bug_and_no_model_is_asked() -> None:
    llm = FakeLLM(BRIEF)

    with pytest.raises(JobError) as raised:
        run_skill(llm, load_skill("brief"), {"idea": ""})

    assert raised.value.error_class is ErrorClass.BUG
    assert llm.requests == []


def test_an_answer_that_fails_the_schema_is_asked_for_once_more_with_the_problems() -> None:
    wrong = {**BRIEF, "titles": ["Only one title"]}
    llm = FakeLLM(wrong, BRIEF)

    result = run_skill(llm, load_skill("brief"), example("brief", "input"))

    first, second = llm.requests
    assert result.output == BRIEF
    assert len(result.calls) == 2, "both calls are kept, so both are recorded and counted"
    assert "not accepted" not in first.prompt
    assert "Your previous answer was not accepted" in second.prompt
    assert "titles" in second.prompt
    assert "A lighthouse keeper who does one small thing" in second.prompt


def test_a_second_failure_ends_the_job_as_invalid_output() -> None:
    wrong = {**BRIEF, "titles": ["Only one title"]}
    llm = FakeLLM(wrong, wrong, BRIEF)

    with pytest.raises(InvalidOutputError, match="twice"):
        run_skill(llm, load_skill("brief"), example("brief", "input"))

    assert len(llm.requests) == 2, "one corrective retry, not more"


def test_an_answer_the_adapter_could_not_read_counts_as_the_first_failure() -> None:
    llm = FakeLLM(InvalidOutputError("The model's answer is not a JSON document."), BRIEF)

    result = run_skill(llm, load_skill("brief"), example("brief", "input"))

    assert result.output == BRIEF
    assert "not a JSON document" in llm.requests[1].prompt


def test_an_answer_that_is_not_an_object_is_refused() -> None:
    llm = FakeLLM(["a", "list"], "just text")

    with pytest.raises(InvalidOutputError):
        run_skill(llm, load_skill("brief"), example("brief", "input"))


# --- research: FR-02 ----------------------------------------------------------------------

CLAIM = {
    "id": "c_habit_66_days",
    "text": "On average a new habit takes about 66 days to form.",
    "source_url": "https://example.org/studies/habits",
    "source_name": "Example University",
    "source_date": "2009-07-16",
    "passage": "The time it took participants to reach automaticity was 66 days on average.",
    "retrieved_at": "2026-11-12T12:00:00+00:00",
}
RETRIEVED = Source(url="https://example.org/studies/habits", title="Habits", cited_text="66 days")


def research(*answers: Any) -> Any:
    return run_skill(
        FakeLLM(*answers),
        load_skill("research"),
        {"brief": BRIEF},
        repair=rules.keep_sourced_claims,
    )


def test_fr02_a_claim_whose_source_was_retrieved_is_kept() -> None:
    result = research(answer({"claims": [CLAIM]}, sources=(RETRIEVED,)))

    (kept,) = result.output["claims"]
    assert {**kept, "retrieved_at": CLAIM["retrieved_at"]} == CLAIM
    assert result.removed == ()


def test_fr02_a_kept_claim_is_stamped_with_the_time_it_was_retrieved() -> None:
    before = datetime.now(UTC).replace(microsecond=0)

    result = research(answer({"claims": [CLAIM]}, sources=(RETRIEVED,)))

    stamped = datetime.fromisoformat(result.output["claims"][0]["retrieved_at"])
    assert before <= stamped <= datetime.now(UTC), "the model's own guess is replaced"


def test_fr02_a_claim_without_a_retrieved_passage_is_rejected() -> None:
    invented = {**CLAIM, "id": "c_from_memory", "source_url": "https://example.org/never-opened"}

    result = research(answer({"claims": [CLAIM, invented]}, sources=(RETRIEVED,)))

    assert [claim["id"] for claim in result.output["claims"]] == [CLAIM["id"]]
    assert len(result.removed) == 1
    assert "c_from_memory" in result.removed[0]


def test_fr02_when_no_claim_has_a_source_the_answer_is_empty_and_says_so() -> None:
    result = research(answer({"claims": [CLAIM]}, sources=()))

    assert result.output["claims"] == []
    assert result.output["note"] == rules.NO_SOURCE_NOTE
    assert len(result.calls) == 1, "dropping a claim is not a reason to ask again"


def test_fr02_an_honest_empty_answer_keeps_its_own_note() -> None:
    result = research({"claims": [], "note": "The story states no facts."})

    assert result.output == {"claims": [], "note": "The story states no facts."}


@pytest.mark.parametrize(
    "written",
    [
        "https://example.org/studies/habits/",
        "http://www.example.org/studies/habits",
        "https://EXAMPLE.org/studies/habits#results",
        "https://example.org/studies/h%61bits",
    ],
)
def test_fr02_the_same_page_written_differently_is_the_same_page(written: str) -> None:
    result = research(answer({"claims": [{**CLAIM, "source_url": written}]}, sources=(RETRIEVED,)))

    assert len(result.output["claims"]) == 1


@pytest.mark.parametrize(
    "written",
    [
        "https://example.org/studies/habits-2",
        "https://example.com/studies/habits",
        "https://example.org/",
    ],
)
def test_fr02_another_page_of_the_same_site_is_not_the_retrieved_page(written: str) -> None:
    result = research(answer({"claims": [{**CLAIM, "source_url": written}]}, sources=(RETRIEVED,)))

    assert result.output["claims"] == []


# --- script: word budget ------------------------------------------------------------------

SCRIPT = example("script", "output")
SCRIPT_INPUT = example("script", "input")


def script(*answers: Any, inputs: dict[str, Any] | None = None) -> Any:
    return run_skill(
        FakeLLM(*answers), load_skill("script"), inputs or SCRIPT_INPUT, check=rules.script_fits
    )


def long_script(words_per_scene: int) -> dict[str, Any]:
    return {
        "scenes": [
            {**scene, "narration": " ".join(["word"] * words_per_scene)}
            for scene in SCRIPT["scenes"]
        ]
    }


@pytest.mark.parametrize(
    ("seconds", "scenes", "speed", "budget"),
    [(45, 7, 1.0, 96), (60, 8, 1.0, 129), (45, 7, 1.2, 116), (45, 7, 0.8, 77), (15, 12, 1.0, 19)],
)
def test_the_word_budget_follows_the_length_the_scenes_and_the_voice(
    seconds: int, scenes: int, speed: float, budget: int
) -> None:
    assert rules.word_budget(seconds, scenes, speed) == budget


def test_the_sample_script_respects_its_word_budget() -> None:
    assert script(SCRIPT).output == SCRIPT


def test_a_script_over_the_word_budget_is_sent_back_with_the_count() -> None:
    llm = FakeLLM(long_script(20), SCRIPT)

    result = run_skill(llm, load_skill("script"), SCRIPT_INPUT, check=rules.script_fits)

    assert result.output == SCRIPT
    assert "has 140 words" in llm.requests[1].prompt
    assert "budget is 96 words" in llm.requests[1].prompt
    assert "Cut 44" in llm.requests[1].prompt


def test_a_script_that_stays_over_the_budget_fails() -> None:
    with pytest.raises(InvalidOutputError, match="140 words"):
        script(long_script(20), long_script(20))


def test_a_script_a_few_words_over_is_left_to_the_resolver() -> None:
    # 14 words in each of 7 scenes is 98: over 96, inside the slack.
    assert len(script(long_script(14)).calls) == 1


def test_a_longer_video_has_a_larger_budget() -> None:
    longer = {**SCRIPT_INPUT, "target_duration_s": 60}

    assert script(long_script(18), inputs=longer).output == long_script(18)


def test_a_script_cannot_use_a_claim_that_research_did_not_return() -> None:
    scenes = [dict(scene) for scene in SCRIPT["scenes"]]
    scenes[3] = {**scenes[3], "beat": "fact", "claim_ids": ["c_made_up"]}

    with pytest.raises(InvalidOutputError, match="c_made_up"):
        script({"scenes": scenes}, {"scenes": scenes})


def test_a_script_may_use_a_claim_that_research_returned() -> None:
    scenes = [dict(scene) for scene in SCRIPT["scenes"]]
    scenes[3] = {**scenes[3], "beat": "fact", "claim_ids": [CLAIM["id"]]}
    inputs = {**SCRIPT_INPUT, "claims": {"claims": [CLAIM]}}

    assert script({"scenes": scenes}, inputs=inputs).output == {"scenes": scenes}


# --- the owner's own lines (VFS-78) ---------------------------------------------------------

# Eight lines of sixteen words: 128 words, where 45 seconds in 8 scenes allow 95.
OWNER_LINES = [
    f"Line {number} is one the owner wrote and wants spoken just as it stands here today."
    for number in ("one", "two", "three", "four", "five", "six", "seven", "eight")
]
# The owner's text as it is pasted: a shot list, with curly quotes around what is spoken.
OWNER_IDEA = "Characters: a father in a dark robe.\n" + "\n".join(
    f"P{index:02d}\tClose-up of the board\t\u201c{line}\u201d"
    for index, line in enumerate(OWNER_LINES, start=1)
)


def owner_script(lines: list[str]) -> dict[str, Any]:
    return {
        "scenes": [
            {"id": f"s{index:02d}_shot", "beat": "story", "narration": line}
            for index, line in enumerate(lines, start=1)
        ]
    }


def test_vfs78_lines_found_in_the_idea_are_the_owners_own() -> None:
    scenes = owner_script(OWNER_LINES)["scenes"]

    assert rules.owner_lines(OWNER_IDEA, scenes) == 8
    assert rules.follows_owner_lines(OWNER_IDEA, scenes)


def test_vfs78_quotes_capitals_and_spacing_do_not_hide_an_owners_line() -> None:
    idea = "He said: \u201cDon\u2019t  fix a man\u2019s pain.\nMake it safe to feel.\u201d"
    scenes = [{"narration": "don't fix a man's pain. make it safe to feel."}]

    assert rules.owner_lines(idea, scenes) == 1


def test_vfs78_a_script_the_model_wrote_is_not_the_owners() -> None:
    assert rules.owner_lines(OWNER_IDEA, SCRIPT["scenes"]) == 0
    assert not rules.follows_owner_lines(OWNER_IDEA, SCRIPT["scenes"])
    assert not rules.follows_owner_lines("", SCRIPT["scenes"])
    # A line of one or two words is found in almost any text. It proves nothing.
    assert rules.owner_lines("He said yes to it.", [{"narration": "yes"}]) == 0


def test_vfs78_the_owners_own_lines_are_not_cut_to_the_word_budget() -> None:
    written = owner_script(OWNER_LINES)
    llm = FakeLLM(written)

    result = run_skill(
        llm,
        load_skill("script"),
        {**SCRIPT_INPUT, "idea": OWNER_IDEA},
        check=rules.script_fits,
    )

    assert result.output == written
    assert len(llm.requests) == 1, "it is not sent back"
    assert "wants spoken just as it stands" in llm.requests[0].prompt


def test_vfs78_one_changed_line_among_the_owners_is_still_the_owners_script() -> None:
    """A name that belongs to someone else is replaced, and that line no longer matches."""
    lines = ["He does what most of us do and he acts as if he were fine.", *OWNER_LINES[1:]]

    given = {**SCRIPT_INPUT, "idea": OWNER_IDEA}

    assert rules.script_fits(given, owner_script(lines), answer({})) == []


def test_vfs78_a_long_script_of_the_models_own_is_still_sent_back() -> None:
    llm = FakeLLM(long_script(20), SCRIPT)

    run_skill(
        llm, load_skill("script"), {**SCRIPT_INPUT, "idea": OWNER_IDEA}, check=rules.script_fits
    )

    assert "has 140 words" in llm.requests[1].prompt


def test_vfs78_the_owners_lines_decide_the_length() -> None:
    scenes = owner_script(OWNER_LINES)["scenes"]

    # 128 words at 2.3 a second and a pause of 0.7 seconds for each of 8 scenes.
    assert rules.owner_length(OWNER_IDEA, scenes) == 61
    assert rules.owner_length(OWNER_IDEA, scenes, speed=1.2) == 52
    assert rules.owner_length(OWNER_IDEA, SCRIPT["scenes"]) is None
    assert rules.owner_length(OWNER_IDEA, owner_script(OWNER_LINES[:1] * 3)["scenes"]) == 23
    many = owner_script([" ".join(["word"] * 80) + f" {n}" for n in range(8)])["scenes"]
    idea = "\n".join(scene["narration"] for scene in many)
    assert rules.owner_length(idea, many) == 180, "never longer than a spec may be"


@pytest.mark.parametrize(
    ("skill", "phrase"),
    [
        ("brief", "If the owner names the episode"),
        ("script", "word for word"),
        ("script", "the owner's own narration"),
        ("script", "belongs to someone else is replaced"),
        ("direct", "the owner's own shot list"),
        ("direct", "one new `generated` asset for each shot"),
        ("assets", "with the owner's words for it"),
        ("assets", "A picture style the owner names"),
        ("assets", "is never written into a prompt"),
    ],
)
def test_vfs78_the_instructions_say_to_keep_what_the_owner_wrote(skill: str, phrase: str) -> None:
    assert phrase in load_skill(skill).instructions


@pytest.mark.parametrize("skill", ["script", "direct", "assets"])
def test_vfs78_the_skills_after_the_brief_accept_the_owners_idea(skill: str) -> None:
    given = {**example(skill, "input"), "idea": OWNER_IDEA}

    result = run_skill(FakeLLM(example(skill, "output")), load_skill(skill), given)

    assert result.output == example(skill, "output")
