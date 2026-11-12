"""The planning jobs on a real Postgres, in demo mode (sections 4.1 and 6, FR-16, FR-17)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers.plan import plan_handlers
from apps.worker.runner import JobContext
from packages.adapters.llm import LLMRequest, LLMResponse, RecordedLLM
from packages.core import queue
from packages.core.db import models
from packages.core.enums import Billing, ErrorClass, JobTag, Provider
from packages.core.queue import JobError
from packages.skills.planner import SKILLS_DIR

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = ROOT / "samples" / "recordings"


def example(skill: str) -> dict[str, Any]:
    path = SKILLS_DIR / skill / "examples" / "lighthouse_keeper.output.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def episode_id(sessions: sessionmaker[Session]) -> uuid.UUID:
    with sessions.begin() as session:
        channel = models.Channel(
            name="Small Steps",
            motto="Small steps still count.",
            voice_id="bm_george",
            theme="night_scrolls",
        )
        session.add(channel)
        session.flush()
        earlier = models.Episode(channel_id=channel.id, idea="An older idea.", title="The Baker")
        episode = models.Episode(channel_id=channel.id, idea="A keeper who climbs a hill.")
        session.add_all([earlier, episode])
        session.flush()
        return episode.id


class Spy:
    """The demo model, with a look at what it was asked."""

    def __init__(self) -> None:
        self.inner = RecordedLLM(RECORDINGS)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return self.inner.complete(request)


def run_job(
    sessions: sessionmaker[Session],
    llm: Spy,
    job_type: str,
    episode_id: uuid.UUID | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Queue one job, run its handler as the worker would, and store the result."""
    with sessions.begin() as session:
        job = queue.enqueue(session, job_type=job_type, tag=JobTag.CPU, payload=payload or {})
        job.episode_id = episode_id
    with sessions.begin() as session:
        claim = queue.claim_next(session, JobTag.CPU)
    assert claim is not None
    handler = plan_handlers(sessions, lambda: llm)[job_type]
    result = handler(JobContext(claim, queue.job_output_path(claim.type, claim.input_hash)))
    output = dict(result or {})
    with sessions.begin() as session:
        queue.complete(session, claim, output)
    return output


def test_fr16_the_three_planning_jobs_run_in_demo_mode_and_build_on_each_other(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    llm = Spy()

    brief = run_job(sessions, llm, "plan.brief", episode_id)
    research = run_job(sessions, llm, "plan.research", episode_id)
    script = run_job(sessions, llm, "plan.script", episode_id)

    assert brief["document"] == example("brief")
    assert research["document"] == example("research")
    assert script["document"] == example("script")
    assert (script["skill"], script["skill_version"]) == ("script", "1.0")
    asked_brief, asked_research, asked_script = llm.requests
    assert "A keeper who climbs a hill." in asked_brief.prompt
    assert "The Baker" in asked_brief.prompt, "past episodes are named so they are not repeated"
    assert "Small steps still count, even when nobody sees them." in asked_research.prompt
    assert '"target_duration_s": 45' in asked_script.prompt
    assert "made-up keeper" in asked_script.prompt, "the script sees what research found"


def test_fr17_every_model_call_of_a_planning_job_is_stored_with_its_job(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    run_job(sessions, Spy(), "plan.brief", episode_id)

    with sessions() as session:
        call = session.scalars(select(models.ModelCall)).one()
        counted = session.scalars(select(models.ProviderUsage)).one()
        job = session.scalars(select(models.Job)).one()
    assert (call.skill, call.skill_version, call.job_id) == ("brief", "1.0", job.id)
    assert (call.provider, call.billing, call.model) == (Provider.DEMO, Billing.DEMO, "recorded")
    assert (call.input_tokens, call.output_tokens) == (640, 150)
    assert counted.job_id == job.id


def test_a_skill_that_needs_an_earlier_result_says_which_one_is_missing(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with pytest.raises(JobError, match="result of 'plan") as raised:
        run_job(sessions, Spy(), "plan.research", episode_id)

    assert raised.value.error_class is ErrorClass.BUG


def test_a_planning_job_without_an_episode_is_a_bug(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(JobError, match="needs an episode"):
        run_job(sessions, Spy(), "plan.brief", None)


def test_the_newest_result_of_a_rerun_state_is_the_one_that_counts(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    llm = Spy()
    run_job(sessions, llm, "plan.brief", episode_id)
    with sessions.begin() as session:
        first = session.scalars(select(models.Job)).one()
        first.output = {
            **(first.output or {}),
            "document": {**example("brief"), "lesson": "An old lesson."},
        }
    run_job(sessions, llm, "plan.brief", episode_id)

    run_job(sessions, llm, "plan.research", episode_id)

    assert "An old lesson." not in llm.requests[-1].prompt


def plan(sessions: sessionmaker[Session], llm: Spy, episode_id: uuid.UUID) -> dict[str, Any]:
    """Run the planning jobs up to the direction and return the direction's result."""
    for job_type in ("plan.brief", "plan.research", "plan.script"):
        run_job(sessions, llm, job_type, episode_id)
    return run_job(sessions, llm, "plan.direct", episode_id)


def test_fr03_the_direction_is_stored_as_the_episodes_first_spec_version(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    directed = plan(sessions, Spy(), episode_id)

    with sessions() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        version = session.scalars(select(models.SpecVersion)).one()
    assert episode.current_spec_id == version.id
    assert (version.version, version.kind.value, version.author.value) == (1, "authored", "model")
    assert (version.skill_version, version.parent_id) == ("1.0", None)
    assert version.body == directed["document"]
    assert directed["spec_version"] == 1


def test_the_spec_carries_what_the_app_knows_and_the_models_direction(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    spec = plan(sessions, Spy(), episode_id)["document"]
    sample = example("direct")

    assert spec["episode_id"] == str(episode_id)
    assert spec["format"] == {"width": 1080, "height": 1920, "fps": 30, "target_duration_s": 45}
    assert spec["voice"] == {"voice_id": "bm_george", "speed": 1.0}
    assert (spec["theme"], spec["spec_version"]) == ("night_scrolls", "2.0")
    assert spec["seed"] == episode_id.int % 2**32
    assert spec["scenes"] == sample["scenes"], "the direction itself is the model's"


def test_directing_again_adds_a_version_that_points_at_the_one_before(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    llm = Spy()
    plan(sessions, llm, episode_id)
    run_job(sessions, llm, "plan.direct", episode_id)

    with sessions() as session:
        first, second = session.scalars(
            select(models.SpecVersion).order_by(models.SpecVersion.version)
        ).all()
        episode = session.get(models.Episode, episode_id)
    assert episode is not None
    assert (second.version, second.parent_id, episode.current_spec_id) == (2, first.id, second.id)


def test_fr16_assets_and_package_follow_from_the_stored_spec(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    llm = Spy()
    plan(sessions, llm, episode_id)

    manifest = run_job(sessions, llm, "plan.assets", episode_id)["document"]
    package = run_job(sessions, llm, "plan.package", episode_id)["document"]

    assert manifest["episode_id"] == str(episode_id)
    assert [entry["id"] for entry in manifest["assets"]] == [
        entry["id"] for entry in example("assets")["assets"]
    ]
    assert package == example("package")
    assert f'"episode_id": "{episode_id}"' in llm.requests[-1].prompt


def test_fr03_a_revision_answers_with_a_patch_and_changes_nothing(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    llm = Spy()
    plan(sessions, llm, episode_id)

    revision = run_job(
        sessions, llm, "plan.revise", episode_id, {"comment": "End the hook with a hard cut."}
    )

    assert revision["document"] == example("revise")
    assert "End the hook with a hard cut." in llm.requests[-1].prompt
    with sessions() as session:
        assert len(session.scalars(select(models.SpecVersion)).all()) == 1, "nothing is applied"


def test_a_revision_without_a_comment_is_a_bug(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    llm = Spy()
    plan(sessions, llm, episode_id)

    with pytest.raises(JobError, match="comment"):
        run_job(sessions, llm, "plan.revise", episode_id)


def test_a_job_that_needs_the_spec_says_so_when_there_is_none(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with pytest.raises(JobError, match="spec"):
        run_job(sessions, Spy(), "plan.assets", episode_id)
