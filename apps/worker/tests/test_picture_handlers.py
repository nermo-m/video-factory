"""The picture jobs on a real Postgres (design doc sections 3.5 and 4.1, FR-06, FR-30)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers.pictures import NO_TEXT, picture_handlers
from apps.worker.runner import JobContext
from packages.adapters.image import ImageRequest, ImageResult, SampleImages
from packages.adapters.storage import LocalStorage
from packages.core import assets, limits, queue
from packages.core.db import models
from packages.core.enums import ErrorClass, JobTag, Provider, SpecAuthor, UsageKind
from packages.core.queue import JobError, PlanLimitError
from packages.core.specs import store_spec
from packages.core.tests.test_assets import own_spec, sample

pytestmark = pytest.mark.integration

__all__ = ["sample"]

PNG = Path(__file__).resolve().parents[3] / "samples/lighthouse_keeper/assets/a_storm_sea.png"


class FakeImages:
    """A picture adapter that remembers what it was asked and answers like a plan would."""

    def __init__(self, error: Exception | None = None) -> None:
        self.requests: list[ImageRequest] = []
        self.error = error

    def create(self, request: ImageRequest) -> ImageResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return ImageResult(
            data=PNG.read_bytes() + bytes([len(self.requests)]),
            width=1122,
            height=1402,
            provider=Provider.CHATGPT_PLAN,
            model="codex image tool",
            cost_usd=Decimal("0"),
            latency_ms=43000,
            licence="Generated on the owner's ChatGPT plan (OpenAI terms of use)",
        )


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def spec(sample: dict[str, Any]) -> dict[str, Any]:
    return own_spec(sample)


@pytest.fixture
def episode_id(sessions: sessionmaker[Session], spec: dict[str, Any], tmp_path: Path) -> uuid.UUID:
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="night_scrolls")
        session.add(channel)
        session.flush()
        episode = models.Episode(channel_id=channel.id, idea="A keeper who climbs a hill.")
        session.add(episode)
        session.flush()
        store_spec(session, episode.id, spec, author=SpecAuthor.MODEL)
        assets.ensure_library(session, LocalStorage(tmp_path / "data"), channel.id)
        assets.sync(session, episode, spec)
        return episode.id


class Stage:
    def __init__(self, sessions: sessionmaker[Session], data_dir: Path, images: Any) -> None:
        self.sessions = sessions
        self.data_dir = data_dir
        self.images = images
        self.handlers = picture_handlers(
            sessions, storage=LocalStorage(data_dir), image=lambda: self.images
        )

    def run(self, job_type: str, episode_id: uuid.UUID, **payload: Any) -> dict[str, Any]:
        tag = JobTag.GPU if job_type == "gen.clip" else JobTag.CPU
        with self.sessions.begin() as session:
            queue.enqueue(
                session, job_type=job_type, tag=tag, payload=payload, episode_id=episode_id
            )
        with self.sessions.begin() as session:
            claim = queue.claim_next(session, tag)
        assert claim is not None
        context = JobContext(claim, queue.job_output_path(claim.type, claim.input_hash))
        output = dict(self.handlers[job_type](context) or {})
        with self.sessions.begin() as session:
            queue.complete(session, claim, output)
        return output


@pytest.fixture
def stage(sessions: sessionmaker[Session], tmp_path: Path) -> Stage:
    return Stage(sessions, tmp_path / "data", FakeImages())


def picture(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any], asset_id: str
) -> assets.Picture:
    with sessions() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        return next(item for item in assets.resolve(session, episode, spec) if item.id == asset_id)


def test_fr06_a_picture_is_made_and_stored_as_a_version_with_its_prompt_and_model(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    output = stage.run("gen.image", episode_id, asset_id="a_harbour")

    now = picture(sessions, episode_id, spec, "a_harbour")
    assert output["made"] is True
    assert output["file"].startswith("jobs/gen.image/")
    assert output["file"].endswith("/a_harbour.png")
    assert (stage.data_dir / output["file"]).read_bytes()[:4] == b"\x89PNG"
    assert now.file == output["file"]
    assert now.version is not None
    assert (now.version.model, now.version.width, now.version.height) == (
        "codex image tool",
        1122,
        1402,
    )
    assert now.version.prompt == f"Prompt in the spec for a_harbour.\n\n{NO_TEXT}"
    assert [request.asset_id for request in stage.images.requests] == ["a_harbour"]
    assert stage.images.requests[0].prompt.endswith(NO_TEXT), "words are drawn by the renderer"


def test_fr31_a_picture_counts_towards_the_providers_image_budget(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    stage.run("gen.image", episode_id, asset_id="a_harbour")

    with sessions() as session:
        counted = session.scalars(select(models.ProviderUsage)).one()
        job = session.scalars(select(models.Job)).one()
    assert (counted.provider, counted.kind, counted.images) == (
        Provider.CHATGPT_PLAN,
        UsageKind.IMAGE,
        1,
    )
    assert counted.job_id == job.id
    assert counted.cost_usd == Decimal("0")
    assert limits.provider_for_job("gen.image", "subscription") is Provider.CHATGPT_PLAN


def test_a_picture_that_has_a_file_is_kept_and_costs_nothing_again(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    first = stage.run("gen.image", episode_id, asset_id="a_harbour")

    again = stage.run("gen.image", episode_id, asset_id="a_harbour", run=2)

    assert again["made"] is False
    assert again["file"] == first["file"]
    assert len(stage.images.requests) == 1
    with sessions() as session:
        assert len(session.scalars(select(models.ProviderUsage)).all()) == 1


def test_fr06_regenerate_makes_a_new_version_and_keeps_the_earlier_one(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    first = stage.run("gen.image", episode_id, asset_id="a_harbour")

    second = stage.run("gen.image", episode_id, asset_id="a_harbour", regenerate=True)

    now = picture(sessions, episode_id, spec, "a_harbour")
    assert second["made"] is True
    assert second["file"] != first["file"]
    assert now.file == second["file"]
    with sessions() as session:
        assert now.asset is not None
        kept = [version.file_path for version in assets.versions(session, now.asset)]
    assert kept == [first["file"], second["file"]]
    assert (stage.data_dir / first["file"]).is_file(), "nothing is deleted"


@pytest.mark.parametrize("asset_id", ["a_hill_dawn", "a_my_photo"])
def test_a_library_or_uploaded_picture_is_not_generated(
    stage: Stage, episode_id: uuid.UUID, asset_id: str
) -> None:
    output = stage.run("gen.image", episode_id, asset_id=asset_id)

    assert output["made"] is False
    assert stage.images.requests == []


def test_a_picture_that_is_not_in_the_spec_is_a_bug(stage: Stage, episode_id: uuid.UUID) -> None:
    with pytest.raises(JobError) as refused:
        stage.run("gen.image", episode_id, asset_id="a_nowhere")

    assert refused.value.error_class is ErrorClass.BUG
    assert "a_nowhere" in str(refused.value)


def test_fr30_a_plan_limit_from_the_adapter_reaches_the_queue_and_stores_nothing(
    sessions: sessionmaker[Session], tmp_path: Path, episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    limited = FakeImages(PlanLimitError("You've hit your usage limit."))
    stage = Stage(sessions, tmp_path / "data", limited)

    with pytest.raises(PlanLimitError):
        stage.run("gen.image", episode_id, asset_id="a_harbour")

    assert picture(sessions, episode_id, spec, "a_harbour").file is None
    with sessions() as session:
        assert session.scalars(select(models.ProviderUsage)).all() == []


def test_demo_mode_makes_a_picture_from_the_bundled_samples(
    sessions: sessionmaker[Session], tmp_path: Path, episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    stage = Stage(sessions, tmp_path / "data", SampleImages())

    output = stage.run("gen.image", episode_id, asset_id="a_harbour")

    assert (output["made"], output["provider"], output["model"]) == (
        True,
        "demo",
        "bundled samples",
    )
    assert picture(sessions, episode_id, spec, "a_harbour").file == output["file"]


def test_a_clip_job_finishes_without_a_clip_and_says_why(
    stage: Stage, episode_id: uuid.UUID
) -> None:
    output = stage.run("gen.clip", episode_id, asset_id="a_harbour", scene_id="s04_storm")

    assert output["made"] is False
    assert output["scene_id"] == "s04_storm"
    assert "still picture" in output["why"]
    assert stage.images.requests == []


def test_a_generated_picture_records_where_it_came_from_and_keeps_its_rights_for_review(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    """Section 5.2: every asset has a licence, and the render refuses one without. The
    licence says where the picture came from. Clearing its rights stays with the owner."""
    before = picture(sessions, episode_id, spec, "a_harbour")
    assert before.asset is not None
    assert before.asset.licence is None

    stage.run("gen.image", episode_id, asset_id="a_harbour")

    after = picture(sessions, episode_id, spec, "a_harbour")
    assert after.asset is not None
    assert after.asset.licence == "Generated on the owner's ChatGPT plan (OpenAI terms of use)"
    assert after.asset.rights_status is before.asset.rights_status


def test_a_licence_that_is_already_recorded_is_kept(
    stage: Stage, sessions: sessionmaker[Session], episode_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    with sessions.begin() as session:
        row = session.get(models.Asset, picture(sessions, episode_id, spec, "a_harbour").asset.id)  # type: ignore[union-attr]
        assert row is not None
        row.licence = "CC0, checked by the owner"

    stage.run("gen.image", episode_id, asset_id="a_harbour")

    kept = picture(sessions, episode_id, spec, "a_harbour").asset
    assert kept is not None
    assert kept.licence == "CC0, checked by the owner"


def test_the_owners_note_is_added_to_the_prompt_of_a_picture_that_is_made_again(
    stage: Stage, episode_id: uuid.UUID
) -> None:
    stage.run("gen.image", episode_id, asset_id="a_harbour")

    stage.run("gen.image", episode_id, asset_id="a_harbour", regenerate=True, note="Make it dawn.")

    first, second = (request.prompt for request in stage.images.requests)
    assert "Make it dawn." not in first
    assert "Prompt in the spec for a_harbour." in second
    assert "Asked for by the owner: Make it dawn." in second
    assert second.endswith(NO_TEXT)
