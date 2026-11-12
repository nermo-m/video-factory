"""Spec versions, diff, replace and patch (design doc sections 4.2, 5 and 10, FR-03)."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from packages.core import json_patch, specs
from packages.core.db import models
from packages.core.enums import EpisodeState, SpecAuthor
from packages.core.specs import Change, SpecError

ROOT = Path(__file__).resolve().parents[3]
SAMPLE: dict[str, Any] = json.loads(
    (ROOT / "samples" / "lighthouse_keeper" / "episode_spec.json").read_text(encoding="utf-8")
)


def edited(change: Any) -> dict[str, Any]:
    spec = copy.deepcopy(SAMPLE)
    change(spec)
    return spec


# --- diff: no database --------------------------------------------------------------------


def test_two_equal_documents_have_no_difference() -> None:
    assert specs.diff(SAMPLE, copy.deepcopy(SAMPLE)) == []


def test_a_changed_value_is_one_replacement_at_its_path() -> None:
    new = edited(lambda spec: spec["scenes"][1].update(narration="She climbed it."))

    assert specs.diff(SAMPLE, new) == [
        Change(
            "replace",
            "/scenes/1/narration",
            old=SAMPLE["scenes"][1]["narration"],
            new="She climbed it.",
        )
    ]


def test_added_and_removed_keys_and_list_items_are_named() -> None:
    def change(spec: dict[str, Any]) -> None:
        spec["scenes"][0]["pad_after_s"] = 0.6
        del spec["scenes"][1]["sublabel"]
        spec["scenes"].pop()

    changes = specs.diff(SAMPLE, edited(change))

    assert [(found.op, found.path) for found in changes] == [
        ("add", "/scenes/0/pad_after_s"),
        ("remove", "/scenes/1/sublabel"),
        ("remove", "/scenes/6"),
    ]
    assert changes[0].new == 0.6
    assert changes[2].old == SAMPLE["scenes"][6]


def test_a_number_that_became_text_is_a_change() -> None:
    assert specs.diff({"a": 1}, {"a": "1"}) == [Change("replace", "/a", old=1, new="1")]
    assert specs.diff({"a": 1}, {"a": True}) == [Change("replace", "/a", old=1, new=True)]


@pytest.mark.parametrize(
    "change",
    [
        lambda spec: spec["scenes"][2].update(narration="Shorter."),
        lambda spec: spec["scenes"].pop(3),
        lambda spec: spec["scenes"].append(copy.deepcopy(spec["scenes"][0])),
        lambda spec: spec.update(seed=99, assets=[]),
        lambda spec: spec["scenes"][1]["overlays"].pop(0),
    ],
)
def test_applying_a_diff_as_a_patch_gives_the_new_document(change: Any) -> None:
    new = edited(change)
    patch = [
        {
            "op": found.op,
            "path": found.path,
            **({} if found.op == "remove" else {"value": found.new}),
        }
        for found in specs.diff(SAMPLE, new)
    ]

    assert json_patch.apply(SAMPLE, patch) == new


def test_names_with_a_slash_are_escaped_in_paths() -> None:
    assert specs.diff({"a/b": 1}, {"a/b": 2}) == [Change("replace", "/a~1b", old=1, new=2)]


# --- versions: real Postgres ----------------------------------------------------------------

integration = pytest.mark.integration


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


@pytest.fixture
def episode_id(sessions: sessionmaker[Session]) -> uuid.UUID:
    with sessions.begin() as session:
        channel = models.Channel(name="Small Steps", voice_id="bm_george", theme="night_scrolls")
        session.add(channel)
        session.flush()
        episode = models.Episode(channel_id=channel.id, idea="A keeper who climbs a hill.")
        session.add(episode)
        session.flush()
        return episode.id


def directed(sessions: sessionmaker[Session], episode_id: uuid.UUID) -> None:
    with sessions.begin() as session:
        specs.store_spec(session, episode_id, SAMPLE, author=SpecAuthor.MODEL, skill_version="1.0")


@integration
def test_fr03_every_change_is_a_new_version_that_points_at_the_one_before(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    directed(sessions, episode_id)
    new = edited(lambda spec: spec["scenes"][1].update(title="THE HILL"))

    with sessions.begin() as session:
        stored = specs.replace_spec(session, episode_id, new, author=SpecAuthor.OWNER)

    with sessions() as session:
        first, second = specs.versions(session, episode_id)
        latest = specs.current(session, episode_id)
    assert latest is not None
    assert (first.version, second.version, latest.id) == (1, 2, stored.id)
    assert (second.parent_id, second.author, second.skill_version) == (
        first.id,
        SpecAuthor.OWNER,
        None,
    )
    assert first.body == SAMPLE, "the earlier version is untouched"


@integration
def test_storing_the_same_spec_again_adds_no_version(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    directed(sessions, episode_id)

    with sessions.begin() as session:
        specs.replace_spec(session, episode_id, copy.deepcopy(SAMPLE), author=SpecAuthor.OWNER)
        assert len(specs.versions(session, episode_id)) == 1


@integration
@pytest.mark.parametrize(
    ("change", "words"),
    [
        (lambda spec: spec["scenes"][0].pop("narration"), "narration"),
        (lambda spec: spec.update(episode_id="ep_another"), "`episode_id` may not be changed"),
        (lambda spec: spec.update(surprise=1), "surprise"),
    ],
)
def test_fr03_a_spec_that_is_not_valid_is_refused_and_nothing_is_stored(
    sessions: sessionmaker[Session], episode_id: uuid.UUID, change: Any, words: str
) -> None:
    directed(sessions, episode_id)

    with sessions.begin() as session, pytest.raises(SpecError) as raised:
        specs.replace_spec(session, episode_id, edited(change), author=SpecAuthor.OWNER)

    assert raised.value.code == "invalid_spec"
    assert any(words in problem for problem in raised.value.problems)
    with sessions() as session:
        assert len(specs.versions(session, episode_id)) == 1


@integration
def test_what_the_theme_cannot_draw_is_refused_with_the_callers_findings(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    directed(sessions, episode_id)
    new = edited(lambda spec: spec["scenes"][0].update(transition_out="cut"))

    with sessions.begin() as session, pytest.raises(SpecError) as raised:
        specs.replace_spec(
            session,
            episode_id,
            new,
            author=SpecAuthor.OWNER,
            capability_problems=["/scenes/0/transition_out: the theme has no transition 'x'"],
        )

    assert raised.value.problems == ["/scenes/0/transition_out: the theme has no transition 'x'"]


@integration
def test_an_episode_without_a_spec_cannot_be_edited(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    with sessions.begin() as session, pytest.raises(SpecError) as raised:
        specs.replace_spec(session, episode_id, SAMPLE, author=SpecAuthor.OWNER)

    assert raised.value.code == "no_spec"


@integration
def test_fr03_a_patch_is_applied_to_the_version_it_was_proposed_for(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    directed(sessions, episode_id)
    patch = [{"op": "replace", "path": "/scenes/0/transition_out", "value": "cut"}]

    with sessions.begin() as session:
        result = specs.patched(session, episode_id, patch, base_version=1)

    assert result["scenes"][0]["transition_out"] == "cut"
    with sessions() as session:
        assert len(specs.versions(session, episode_id)) == 1, "nothing is stored by looking"


@integration
def test_fr03_a_patch_for_an_older_version_is_refused(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    directed(sessions, episode_id)
    with sessions.begin() as session:
        specs.replace_spec(
            session,
            episode_id,
            edited(lambda spec: spec.update(seed=8)),
            author=SpecAuthor.OWNER,
        )
    patch = [{"op": "replace", "path": "/scenes/0/transition_out", "value": "cut"}]

    with sessions.begin() as session, pytest.raises(SpecError) as raised:
        specs.patched(session, episode_id, patch, base_version=1)

    assert raised.value.code == "spec_changed"
    assert "version 2" in str(raised.value)


@integration
def test_a_patch_that_does_not_apply_is_refused(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    directed(sessions, episode_id)

    with sessions.begin() as session, pytest.raises(SpecError) as raised:
        specs.patched(session, episode_id, [{"op": "remove", "path": "/scenes/40"}], base_version=1)

    assert raised.value.code == "invalid_patch"


@integration
def test_an_edit_after_the_plan_gate_marks_the_changed_scene_stale(
    sessions: sessionmaker[Session], episode_id: uuid.UUID
) -> None:
    directed(sessions, episode_id)
    with sessions.begin() as session:
        episode = session.get(models.Episode, episode_id)
        assert episode is not None
        episode.state = EpisodeState.RENDER
        for state in ("voice", "render"):
            session.add(
                models.Job(
                    episode_id=episode_id,
                    type=f"x.{state}",
                    tag="cpu",
                    status="succeeded",
                    input={"state": state, "stage": 0, "run": 1},
                )
            )
    new = edited(lambda spec: spec["scenes"][2].update(narration="He cleaned the glass again."))

    with sessions.begin() as session:
        specs.replace_spec(session, episode_id, new, author=SpecAuthor.OWNER)

    with sessions() as session:
        episode = session.get(models.Episode, episode_id)
    assert episode is not None
    assert "s03_lamp" in episode.stale_scenes.get("voice", [])
    assert episode.stale_from_state is EpisodeState.VOICE
