"""The shot list job on a real Postgres (Director mode: the owner's prompt is the plan)."""

from __future__ import annotations

import copy
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers.plan import plan_handlers
from apps.worker.handlers.shotlist import SHOTLIST_JOB, shotlist_handlers
from apps.worker.runner import JobContext
from packages.adapters.llm import LLMRequest, LLMResponse, RecordedLLM
from packages.adapters.storage import LocalStorage
from packages.core import assets, queue, schemas, specs
from packages.core.db import models
from packages.core.enums import ErrorClass, JobTag, Provider, SpecAuthor
from packages.core.queue import JobError
from packages.render.theme import check_capabilities, load_theme
from packages.skills.planner import SKILLS_DIR

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = ROOT / "samples" / "recordings"
EXAMPLES = SKILLS_DIR / "shotlist" / "examples"


def example(part: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (EXAMPLES / f"lighthouse_keeper.{part}.json").read_text(encoding="utf-8")
    )
    return loaded


IDEA: str = example("input")["idea"]


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


def new_episode(sessions: sessionmaker[Session], idea: str = IDEA, **fields: Any) -> uuid.UUID:
    with sessions.begin() as session:
        channel = models.Channel(
            name="My channel",
            voice_id="bm_george",
            theme="night_scrolls",
            style_block="Always in the house style of the channel.",
        )
        session.add(channel)
        session.flush()
        made = models.Episode(channel_id=channel.id, idea=idea, **fields)
        session.add(made)
        session.flush()
        return made.id


class Model:
    """A model that answers with a given shot list, as a live plan would, and keeps what
    it was asked."""

    def __init__(self, *answers: dict[str, Any], provider: Provider = Provider.CLAUDE_PLAN) -> None:
        self.answers = list(answers)
        self.provider = provider
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        answer = self.answers[min(len(self.requests), len(self.answers)) - 1]
        return LLMResponse(
            output=copy.deepcopy(answer),
            text=json.dumps(answer),
            provider=self.provider,
            model="test",
            input_tokens=10,
            output_tokens=10,
            cost_usd=Decimal("0"),
            latency_ms=1,
        )


def run(
    sessions: sessionmaker[Session],
    llm: Any,
    episode_id: uuid.UUID,
    *,
    job_type: str = SHOTLIST_JOB,
    payload: dict[str, Any] | None = None,
    storage: LocalStorage | None = None,
) -> dict[str, Any]:
    with sessions.begin() as session:
        queue.enqueue(
            session, job_type=job_type, tag=JobTag.CPU, payload=payload, episode_id=episode_id
        )
    with sessions.begin() as session:
        claim = queue.claim_next(session, JobTag.CPU)
    assert claim is not None
    handlers = {
        **plan_handlers(sessions, lambda: llm, storage),
        **shotlist_handlers(sessions, lambda: llm),
    }
    output = dict(handlers[job_type](JobContext(claim, queue.output_path_of(claim))) or {})
    with sessions.begin() as session:
        queue.complete(session, claim, output)
    return output


def plan_of(sessions: sessionmaker[Session], episode_id: uuid.UUID) -> dict[str, Any]:
    with sessions() as session:
        current = specs.current(session, episode_id)
        assert current is not None
        return dict(current.body)


def silent(*seconds: float) -> dict[str, Any]:
    """A shot list of silent scenes, each this many seconds long."""
    base = example("output")["scenes"][0]
    scenes = []
    for index, length in enumerate(seconds):
        scene = {**copy.deepcopy(base), "id": f"shot_{index}", "narration": "", "characters": []}
        scene.pop("narration_from", None)
        scene["duration_s"] = length
        scenes.append(scene)
    return {**example("output"), "characters": [], "changes": [], "scenes": scenes}


# --- the plan ------------------------------------------------------------------------------


def test_the_shot_list_job_stores_a_2_1_plan_names_the_episode_and_creates_its_picture_rows(
    sessions: sessionmaker[Session],
) -> None:
    episode_id = new_episode(sessions)

    output = run(sessions, Model(example("output")), episode_id)

    plan = plan_of(sessions, episode_id)
    assert schemas.validate("episode_spec", plan) == []
    assert check_capabilities(plan, load_theme("plain").capabilities) == []
    assert (plan["spec_version"], plan["theme"]) == ("2.1", "plain")
    assert plan["episode_id"] == str(episode_id)
    assert [scene["narration"] for scene in plan["scenes"]] == [
        scene["narration"] for scene in example("output")["scenes"]
    ]
    assert (output["skill"], output["skill_version"]) == ("shotlist", "1.0")
    assert output["document"] == example("output")
    assert output["spec_version"] == 1
    with sessions() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        version = session.get(models.SpecVersion, episode.current_spec_id)
        assert version is not None
        pictures = assets.resolve(session, episode, plan)
    assert episode.title == "The Keeper's Hill"
    # 66 words at 2.3 a second, four pauses of 0.7 seconds and the 3 silent seconds.
    assert episode.target_duration_s == plan["format"]["target_duration_s"] == 35
    assert (version.author, version.skill_version) == (SpecAuthor.MODEL, "1.0")
    assert [picture.id for picture in pictures] == [asset["id"] for asset in plan["assets"]]
    assert all(picture.asset is not None for picture in pictures)
    assert all(picture.version is None for picture in pictures), "nothing is generated yet"


def test_the_model_is_given_the_owners_whole_prompt_and_the_plain_look(
    sessions: sessionmaker[Session],
) -> None:
    episode_id = new_episode(sessions)
    llm = Model(example("output"))

    run(sessions, llm, episode_id)

    (asked,) = llm.requests
    sent = json.loads(asked.prompt.removeprefix("Input:\n"))
    assert sent["idea"] == IDEA
    assert sent["capabilities"] == load_theme("plain").capabilities
    assert sent["claims"] == []
    assert "comment" not in sent
    assert asked.skill == "shotlist"
    assert "house style of the channel" not in asked.prompt


def test_a_title_the_episode_already_has_is_kept(sessions: sessionmaker[Session]) -> None:
    episode_id = new_episode(sessions, title="My own title")

    run(sessions, Model(example("output")), episode_id)

    with sessions() as session:
        episode = session.get(models.Episode, episode_id)
    assert episode is not None
    assert episode.title == "My own title"


def test_the_switches_of_the_episode_reach_the_plan(sessions: sessionmaker[Session]) -> None:
    episode_id = new_episode(sessions, options={"captions": False, "music": False})

    run(sessions, Model(example("output")), episode_id)

    plan = plan_of(sessions, episode_id)
    assert (plan["captions"], plan["music"]) == (False, False)


def test_a_video_has_captions_and_music_unless_the_owner_switched_them_off(
    sessions: sessionmaker[Session],
) -> None:
    episode_id = new_episode(sessions)

    run(sessions, Model(example("output")), episode_id)

    plan = plan_of(sessions, episode_id)
    assert (plan["captions"], plan["music"]) == (True, True)


def test_planning_again_adds_a_version_and_keeps_the_picture_rows(
    sessions: sessionmaker[Session],
) -> None:
    episode_id = new_episode(sessions)
    run(sessions, Model(example("output")), episode_id)

    second = run(sessions, Model(example("output")), episode_id)

    assert second["spec_version"] == 2
    with sessions() as session:
        rows = session.scalars(
            select(models.Asset).where(models.Asset.episode_id == episode_id)
        ).all()
    assert len(rows) == len(example("output")["scenes"])


def test_the_owners_comment_after_a_rejection_reaches_the_model(
    sessions: sessionmaker[Session],
) -> None:
    episode_id = new_episode(sessions)
    llm = Model(example("output"))

    run(sessions, llm, episode_id, payload={"comment": "  Make the storm scene darker. "})

    sent = json.loads(llm.requests[0].prompt.removeprefix("Input:\n"))
    assert sent["comment"] == "Make the storm scene darker."


# --- the owner's prompt is the plan --------------------------------------------------------


def test_a_plan_that_drops_one_of_the_owners_lines_is_sent_back_once_and_then_fails(
    sessions: sessionmaker[Session],
) -> None:
    episode_id = new_episode(sessions)
    shortened = example("output")
    shortened["scenes"][1]["narration"] = "He cleaned the glass."
    llm = Model(shortened)

    with pytest.raises(JobError) as raised:
        run(sessions, llm, episode_id)

    assert raised.value.error_class is ErrorClass.INVALID_OUTPUT
    assert len(llm.requests) == 2
    assert "does not stand in the owner's prompt word for word" in llm.requests[1].prompt
    with sessions() as session:
        assert specs.current(session, episode_id) is None


def test_a_plan_that_is_put_right_on_the_second_try_is_stored(
    sessions: sessionmaker[Session],
) -> None:
    episode_id = new_episode(sessions)
    shortened = example("output")
    shortened["scenes"][1]["narration"] = "He cleaned the glass."
    llm = Model(shortened, example("output"))

    run(sessions, llm, episode_id)

    assert len(llm.requests) == 2
    assert plan_of(sessions, episode_id)["scenes"][1]["narration"].startswith("He trimmed the wick")


def test_a_silent_prompt_reaches_the_plan(sessions: sessionmaker[Session]) -> None:
    episode_id = new_episode(sessions, idea="Three pictures of a hill. Four seconds each.")

    run(sessions, Model(silent(4, 4, 4)), episode_id)

    plan = plan_of(sessions, episode_id)
    assert [scene["narration"] for scene in plan["scenes"]] == ["", "", ""]
    assert [scene["duration_s"] for scene in plan["scenes"]] == [4, 4, 4]
    assert plan["format"]["target_duration_s"] == 15


def test_lines_longer_than_180_seconds_stop_the_job_for_the_owner(
    sessions: sessionmaker[Session],
) -> None:
    episode_id = new_episode(sessions, idea="Ten long pictures of a hill.")

    with pytest.raises(JobError) as raised:
        run(sessions, Model(silent(*([30] * 7))), episode_id)

    assert raised.value.error_class is ErrorClass.NEEDS_OWNER
    assert str(raised.value) == (
        "Your lines need about 210 seconds and a video can be 180 at most. "
        "Shorten the prompt or split it into two videos."
    )
    with sessions() as session:
        assert specs.current(session, episode_id) is None


# --- demo mode -----------------------------------------------------------------------------


def test_fr16_in_demo_mode_any_idea_gets_the_recorded_sample_plan(
    sessions: sessionmaker[Session],
) -> None:
    """Demo mode has one recording, the sample story, whatever was typed. It is not held
    against the typed idea: it could never pass, and the screens say that it is recorded."""
    episode_id = new_episode(sessions, idea="A baker who gives away the first loaf.")

    output = run(sessions, RecordedLLM(RECORDINGS), episode_id)

    assert output["document"] == example("output")
    assert plan_of(sessions, episode_id)["scenes"][0]["id"] == "hill_dawn"


# --- research is a choice ------------------------------------------------------------------


def test_research_reads_the_owners_prompt_and_its_claims_reach_the_shot_list(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    episode_id = new_episode(sessions, options={"research": True})
    recorded = RecordedLLM(RECORDINGS)
    storage = LocalStorage(tmp_path / "data")

    research = run(sessions, recorded, episode_id, job_type="plan.research", storage=storage)
    llm = Model(example("output"))
    run(sessions, llm, episode_id)

    claims = research["document"]["claims"]
    sent = json.loads(llm.requests[0].prompt.removeprefix("Input:\n"))
    assert sent["claims"] == claims
    assert plan_of(sessions, episode_id)["claims"] == claims


def test_without_research_there_are_no_claims(sessions: sessionmaker[Session]) -> None:
    episode_id = new_episode(sessions)

    run(sessions, Model(example("output")), episode_id)

    assert plan_of(sessions, episode_id)["claims"] == []
