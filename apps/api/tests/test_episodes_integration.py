"""The episode routes on a real Postgres, with a worker in demo mode (sections 4 and 10)."""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.episodes import DatabaseEpisodeService
from apps.api.health import Check, CheckStatus, HealthChecks
from apps.api.main import create_app
from apps.api.providers import MemoryProviderService
from apps.api.settings import MemorySettingStore
from apps.worker.handlers.plan import plan_handlers
from apps.worker.tests.test_worker import running_worker
from packages.adapters.llm import RecordedLLM
from packages.core.db import models
from packages.core.settings import Settings

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = ROOT / "samples" / "recordings"
IDEA = "A lighthouse keeper who does one small thing every day."


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def client(sessions: sessionmaker[Session], database_url: str) -> TestClient:
    def ok() -> Check:
        return Check(status=CheckStatus.OK)

    return TestClient(
        create_app(
            Settings(database_url=database_url),
            checks=HealthChecks(database=ok, storage=ok, comfyui=ok),
            setting_store=MemorySettingStore(),
            provider_service=MemoryProviderService(),
            episode_service=DatabaseEpisodeService(sessions),
        )
    )


@pytest.fixture
def worker(sessions: sessionmaker[Session]) -> Iterator[None]:
    """A worker that plans with the demo recordings."""
    handlers = plan_handlers(sessions, lambda: RecordedLLM(RECORDINGS))
    with running_worker(sessions, handlers):
        yield


def wait_for(condition: Callable[[], bool], seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "the episode did not get there in time"
        time.sleep(0.05)


def episode(client: TestClient, episode_id: str) -> dict[str, Any]:
    body: dict[str, Any] = client.get(f"/api/v1/episodes/{episode_id}").json()
    return body


def planned(client: TestClient) -> str:
    """Create an episode and wait until its plan is at the gate. Needs the worker."""
    created = client.post("/api/v1/episodes", json={"idea": IDEA}).json()
    wait_for(lambda: episode(client, created["id"])["awaiting_approval"])
    return str(created["id"])


def test_creating_an_episode_starts_its_plan(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    response = client.post("/api/v1/episodes", json={"idea": f"  {IDEA} ", "target_duration_s": 60})

    body = response.json()
    assert response.status_code == 201
    assert (body["idea"], body["state"], body["target_duration_s"]) == (IDEA, "brief", 60)
    assert (body["awaiting_approval"], body["gate"], body["spec_version"]) == (False, None, None)
    assert [(job["type"], job["status"]) for job in body["jobs"]] == [("plan.brief", "queued")]
    with sessions() as session:
        channel = session.scalars(select(models.Channel)).one()
    assert (channel.theme, channel.voice_id) == ("night_scrolls", "bm_george")


def test_an_episode_can_be_created_without_starting_it(client: TestClient) -> None:
    body = client.post("/api/v1/episodes", json={"idea": IDEA, "start": False}).json()

    assert (body["state"], body["jobs"]) == ("idea", [])

    advanced = client.post(f"/api/v1/episodes/{body['id']}/advance").json()
    assert advanced["state"] == "brief"


def test_every_episode_shares_the_one_default_channel(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    for _ in range(3):
        client.post("/api/v1/episodes", json={"idea": IDEA, "start": False})

    with sessions() as session:
        assert len(session.scalars(select(models.Channel)).all()) == 1


def test_the_board_lists_episodes_newest_first_in_pages(client: TestClient) -> None:
    ids = [
        client.post("/api/v1/episodes", json={"idea": f"Idea {n}", "start": False}).json()["id"]
        for n in range(5)
    ]

    first = client.get("/api/v1/episodes", params={"limit": 2}).json()
    rest = client.get("/api/v1/episodes", params={"limit": 2, "offset": 4}).json()

    assert (first["total"], first["limit"], first["offset"]) == (5, 2, 0)
    assert [found["id"] for found in first["episodes"]] == [ids[4], ids[3]]
    assert [found["id"] for found in rest["episodes"]] == [ids[0]]
    assert "jobs" not in first["episodes"][0], "the list stays light"


@pytest.mark.usefixtures("worker")
def test_fr16_in_demo_mode_an_idea_reaches_the_plan_gate_by_itself(client: TestClient) -> None:
    episode_id = planned(client)

    body = episode(client, episode_id)
    assert (body["state"], body["gate"], body["spec_version"]) == ("direction", "plan", 1)
    finished = {job["type"]: job["status"] for job in body["jobs"]}
    assert finished == {
        "plan.brief": "succeeded",
        "plan.research": "succeeded",
        "plan.script": "succeeded",
        "plan.direct": "succeeded",
    }
    spec = client.get(f"/api/v1/episodes/{episode_id}/spec").json()
    assert (spec["version"], spec["author"], spec["skill_version"]) == (1, "model", "1.2")
    assert spec["spec"]["episode_id"] == episode_id
    assert spec["spec"]["scenes"][0]["id"] == "s01_hook"


@pytest.mark.usefixtures("worker")
def test_fr03_the_owner_edits_the_spec_and_sees_what_changed(client: TestClient) -> None:
    episode_id = planned(client)
    spec = client.get(f"/api/v1/episodes/{episode_id}/spec").json()["spec"]
    edited = copy.deepcopy(spec)
    edited["scenes"][0]["transition_out"] = "cut"

    stored = client.put(f"/api/v1/episodes/{episode_id}/spec", json=edited)
    versions = client.get(f"/api/v1/episodes/{episode_id}/spec/versions").json()["versions"]
    diff = client.get(
        f"/api/v1/episodes/{episode_id}/spec/diff", params={"from": 1, "to": 2}
    ).json()

    assert (stored.status_code, stored.json()["version"], stored.json()["author"]) == (
        200,
        2,
        "owner",
    )
    assert [(found["version"], found["current"]) for found in versions] == [(1, False), (2, True)]
    assert diff == {
        "from_version": 1,
        "to_version": 2,
        "changes": [
            {"op": "replace", "path": "/scenes/0/transition_out", "old": "smoke", "new": "cut"}
        ],
    }


@pytest.mark.usefixtures("worker")
@pytest.mark.parametrize(
    ("change", "words"),
    [
        (lambda spec: spec["scenes"][0].pop("narration"), "narration"),
        (lambda spec: spec["scenes"][0].update(transition_out="wipe"), "the theme has no"),
        (lambda spec: spec.update(episode_id="ep_another"), "may not be changed"),
        (lambda spec: spec.update(theme="no_such_theme"), "no theme"),
    ],
)
def test_fr03_a_spec_that_cannot_be_used_is_refused_with_every_problem(
    client: TestClient, change: Any, words: str
) -> None:
    episode_id = planned(client)
    spec = client.get(f"/api/v1/episodes/{episode_id}/spec").json()["spec"]
    change(spec)

    response = client.put(f"/api/v1/episodes/{episode_id}/spec", json=spec)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_spec"
    assert any(words in problem for problem in response.json()["error"]["details"]["problems"])
    assert client.get(f"/api/v1/episodes/{episode_id}/spec").json()["version"] == 1


@pytest.mark.usefixtures("worker")
def test_fr03_a_revision_is_proposed_shown_and_then_applied(client: TestClient) -> None:
    episode_id = planned(client)

    asked = client.post(
        f"/api/v1/episodes/{episode_id}/revise", json={"comment": " End the hook with a cut. "}
    )
    job_id = asked.json()["job_id"]
    revision_url = f"/api/v1/episodes/{episode_id}/revisions/{job_id}"
    wait_for(lambda: client.get(revision_url).json()["status"] == "succeeded")
    proposal = client.get(revision_url).json()
    before = client.get(f"/api/v1/episodes/{episode_id}/spec").json()

    applied = client.post(f"/api/v1/episodes/{episode_id}/revise/apply", json={"job_id": job_id})

    assert (asked.status_code, asked.json()["status"], asked.json()["can_apply"]) == (
        202,
        "queued",
        False,
    )
    assert (proposal["comment"], proposal["base_version"]) == ("End the hook with a cut.", 1)
    assert proposal["summary"] == "The hook now ends with a hard cut instead of smoke."
    assert proposal["changes"] == [
        {"op": "replace", "path": "/scenes/0/transition_out", "old": "smoke", "new": "cut"}
    ]
    assert proposal["can_apply"] is True
    assert before["version"] == 1, "looking at a proposal changes nothing"
    assert (applied.status_code, applied.json()["version"], applied.json()["author"]) == (
        200,
        2,
        "model",
    )
    assert applied.json()["spec"]["scenes"][0]["transition_out"] == "cut"


@pytest.mark.usefixtures("worker")
def test_fr03_a_revision_for_an_older_version_can_no_longer_be_applied(client: TestClient) -> None:
    episode_id = planned(client)
    job_id = client.post(
        f"/api/v1/episodes/{episode_id}/revise", json={"comment": "End the hook with a cut."}
    ).json()["job_id"]
    revision_url = f"/api/v1/episodes/{episode_id}/revisions/{job_id}"
    wait_for(lambda: client.get(revision_url).json()["status"] == "succeeded")
    spec = client.get(f"/api/v1/episodes/{episode_id}/spec").json()["spec"]
    spec["seed"] = 8
    client.put(f"/api/v1/episodes/{episode_id}/spec", json=spec)

    proposal = client.get(revision_url).json()
    applied = client.post(f"/api/v1/episodes/{episode_id}/revise/apply", json={"job_id": job_id})

    assert (proposal["can_apply"], proposal["changes"]) == (False, None)
    assert "version 2" in proposal["message"]
    assert (applied.status_code, applied.json()["error"]["code"]) == (409, "spec_changed")


@pytest.mark.usefixtures("worker")
def test_the_gate_is_passed_by_approving_and_only_then(client: TestClient) -> None:
    episode_id = planned(client)

    held = client.post(f"/api/v1/episodes/{episode_id}/advance")
    approved = client.post(f"/api/v1/episodes/{episode_id}/approve")
    again = client.post(f"/api/v1/episodes/{episode_id}/approve")

    assert (held.status_code, held.json()["error"]["code"]) == (409, "awaiting_approval")
    assert (approved.status_code, approved.json()["state"]) == (200, "asset_plan")
    assert approved.json()["awaiting_approval"] is False
    assert (again.status_code, again.json()["error"]["code"]) == (409, "not_awaiting_approval")


@pytest.mark.usefixtures("worker")
def test_a_rejection_runs_the_plan_again_with_the_owners_comment(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    episode_id = planned(client)

    rejected = client.post(
        f"/api/v1/episodes/{episode_id}/reject", json={"comment": "Too slow in the middle."}
    )

    assert (rejected.status_code, rejected.json()["state"]) == (200, "direction")
    assert rejected.json()["awaiting_approval"] is False
    with sessions() as session:
        newest = session.scalars(
            select(models.Job)
            .where(models.Job.episode_id == uuid.UUID(episode_id))
            .order_by(models.Job.created_at.desc())
        ).first()
    assert newest is not None
    assert newest.input["comment"] == "Too slow in the middle."


@pytest.mark.usefixtures("worker")
def test_a_state_can_be_run_again(client: TestClient) -> None:
    episode_id = planned(client)

    rerun = client.post(f"/api/v1/episodes/{episode_id}/rerun", json={"state": "script"})

    assert (rerun.status_code, rerun.json()["state"]) == (200, "script")
    wait_for(lambda: episode(client, episode_id)["awaiting_approval"])
    assert episode(client, episode_id)["spec_version"] == 2, "directed again, as a new version"


def test_before_the_plan_is_directed_there_is_no_spec(client: TestClient) -> None:
    episode_id = client.post("/api/v1/episodes", json={"idea": IDEA, "start": False}).json()["id"]

    for method, path, body in (
        ("get", "spec", None),
        ("put", "spec", {"any": "thing"}),
        ("post", "revise", {"comment": "Shorter."}),
    ):
        response = getattr(client, method)(
            f"/api/v1/episodes/{episode_id}/{path}", **({"json": body} if body else {})
        )
        assert (response.status_code, response.json()["error"]["code"]) == (404, "no_spec"), path
    versions = client.get(f"/api/v1/episodes/{episode_id}/spec/versions")
    assert versions.json() == {"versions": []}


@pytest.mark.usefixtures("worker")
def test_what_does_not_exist_is_not_found(client: TestClient) -> None:
    episode_id = planned(client)
    other = uuid.uuid4()

    missing_version = client.get(
        f"/api/v1/episodes/{episode_id}/spec/diff", params={"from": 1, "to": 9}
    )
    missing_revision = client.get(f"/api/v1/episodes/{episode_id}/revisions/{other}")
    missing_apply = client.post(
        f"/api/v1/episodes/{episode_id}/revise/apply", json={"job_id": str(other)}
    )

    assert (missing_version.status_code, missing_version.json()["error"]["code"]) == (
        404,
        "version_not_found",
    )
    assert missing_revision.json()["error"]["code"] == "revision_not_found"
    assert missing_apply.json()["error"]["code"] == "revision_not_found"
    for method, path in (
        ("get", ""),
        ("post", "/advance"),
        ("post", "/approve"),
        ("get", "/spec"),
        ("get", "/spec/versions"),
    ):
        response = getattr(client, method)(f"/api/v1/episodes/{other}{path}")
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "episode_not_found",
        ), path


@pytest.mark.usefixtures("worker")
def test_the_plan_shows_the_brief_and_how_long_each_scene_is_estimated_to_take(
    client: TestClient,
) -> None:
    episode_id = planned(client)

    answer = client.get(f"/api/v1/episodes/{episode_id}/plan")

    body = answer.json()
    assert answer.status_code == 200
    assert set(body["brief"]) >= {"angle", "lesson", "audience", "titles"}
    spec = client.get(f"/api/v1/episodes/{episode_id}/spec").json()["spec"]
    assert [scene["id"] for scene in body["scenes"]] == [scene["id"] for scene in spec["scenes"]]
    assert all(scene["estimated_s"] > 0 and scene["words"] > 0 for scene in body["scenes"])
    assert body["estimated_total_s"] == pytest.approx(
        sum(scene["estimated_s"] for scene in body["scenes"]), abs=0.5
    )
    assert body["target_duration_s"] == 45
    assert body["shortest_s"] < 45 < body["longest_s"]
    assert body["fits"] is True


@pytest.mark.usefixtures("worker")
def test_the_plan_estimate_follows_an_edit_of_the_narration(client: TestClient) -> None:
    episode_id = planned(client)
    before = client.get(f"/api/v1/episodes/{episode_id}/plan").json()
    spec = client.get(f"/api/v1/episodes/{episode_id}/spec").json()["spec"]
    spec["scenes"][1]["narration"] += " " + " ".join(["more"] * 46)

    assert client.put(f"/api/v1/episodes/{episode_id}/spec", json=spec).status_code == 200

    after = client.get(f"/api/v1/episodes/{episode_id}/plan").json()
    assert after["scenes"][1]["words"] == before["scenes"][1]["words"] + 46
    assert after["scenes"][1]["estimated_s"] == pytest.approx(
        before["scenes"][1]["estimated_s"] + 20, abs=0.11
    )
    assert after["fits"] is False


def test_before_the_plan_is_written_the_plan_is_empty_and_says_nothing_about_fit(
    client: TestClient,
) -> None:
    created = client.post("/api/v1/episodes", json={"idea": "Not started.", "start": False}).json()

    body = client.get(f"/api/v1/episodes/{created['id']}/plan").json()

    assert (body["brief"], body["scenes"], body["estimated_total_s"], body["fits"]) == (
        None,
        [],
        None,
        None,
    )
    assert client.get(f"/api/v1/episodes/{uuid.uuid4()}/plan").status_code == 404
