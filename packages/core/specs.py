"""Versions of an episode's authored spec (design doc sections 5, 9 and 10, FR-03).

A spec is never changed in place. Every change is a new `spec_version` row that points at
the one before it, and the episode points at its current one. So any version can be read
again and any two can be compared.

Every change of the spec goes through here, whoever makes it: the director skill, the
owner's edit, or a revision the owner applied. After the plan is approved, a change also
marks the scenes it made stale (section 4.2). The functions take a Session and never
commit.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.core import json_patch, pipeline, schemas
from packages.core.db.models import Episode, SpecVersion
from packages.core.enums import SpecAuthor, SpecKind

# What an edit may not change: these belong to the episode and its channel.
PROTECTED = ("spec_version", "episode_id")


class SpecError(Exception):
    """A spec change that cannot be made. `code` is stable, `problems` lists what is wrong."""

    def __init__(self, code: str, message: str, problems: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.problems = list(problems)


@dataclass(frozen=True)
class Change:
    """One difference between two specs. `path` is a JSON Pointer."""

    op: str  # add, remove or replace
    path: str
    old: Any = None
    new: Any = None


def _escape(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def diff(old: Any, new: Any, path: str = "") -> list[Change]:
    """What changed from one document to another, deepest difference first found.

    Lists are compared position by position. A list that grew or shrank shows its extra
    items as added or removed at the end.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        changes: list[Change] = []
        for key in old:
            here = f"{path}/{_escape(str(key))}"
            if key not in new:
                changes.append(Change("remove", here, old=old[key]))
            else:
                changes += diff(old[key], new[key], here)
        for key in new:
            if key not in old:
                changes.append(Change("add", f"{path}/{_escape(str(key))}", new=new[key]))
        return changes
    if isinstance(old, list) and isinstance(new, list):
        changes = []
        for index in range(min(len(old), len(new))):
            changes += diff(old[index], new[index], f"{path}/{index}")
        # Removed from the end backwards, so the changes can be applied in this order.
        for index in range(len(old) - 1, len(new) - 1, -1):
            changes.append(Change("remove", f"{path}/{index}", old=old[index]))
        for index in range(len(old), len(new)):
            changes.append(Change("add", f"{path}/{index}", new=new[index]))
        return changes
    if old != new or type(old) is not type(new):
        return [Change("replace", path, old=old, new=new)]
    return []


def versions(session: Session, episode_id: uuid.UUID) -> list[SpecVersion]:
    """Every authored version of the episode's spec, oldest first."""
    return list(
        session.scalars(
            select(SpecVersion)
            .where(SpecVersion.episode_id == episode_id, SpecVersion.kind == SpecKind.AUTHORED)
            .order_by(SpecVersion.version)
        )
    )


def version(session: Session, episode_id: uuid.UUID, number: int) -> SpecVersion | None:
    return session.scalar(
        select(SpecVersion).where(
            SpecVersion.episode_id == episode_id,
            SpecVersion.version == number,
            SpecVersion.kind == SpecKind.AUTHORED,
        )
    )


def current(session: Session, episode_id: uuid.UUID) -> SpecVersion | None:
    episode = session.get(Episode, episode_id)
    if episode is None or episode.current_spec_id is None:
        return None
    return session.get(SpecVersion, episode.current_spec_id)


def store_spec(
    session: Session,
    episode_id: uuid.UUID,
    body: Mapping[str, Any],
    *,
    author: SpecAuthor,
    skill_version: str | None = None,
) -> SpecVersion:
    """Add a version of the episode's authored spec and make it the current one."""
    episode = session.get(Episode, episode_id, with_for_update=True)
    if episode is None:
        raise SpecError("not_found", "This episode does not exist.")
    newest = session.scalar(
        select(func.max(SpecVersion.version)).where(SpecVersion.episode_id == episode_id)
    )
    stored = SpecVersion(
        episode_id=episode_id,
        version=(newest or 0) + 1,
        kind=SpecKind.AUTHORED,
        body=dict(body),
        author=author,
        skill_version=skill_version,
        parent_id=episode.current_spec_id,
    )
    session.add(stored)
    session.flush()
    episode.current_spec_id = stored.id
    return stored


def _checked(body: Mapping[str, Any], before: Mapping[str, Any], drawable: Sequence[str]) -> None:
    """Raise SpecError unless `body` is a valid spec for the same episode."""
    problems = [str(found) for found in schemas.validate("episode_spec", dict(body))]
    if problems:
        raise SpecError("invalid_spec", "The spec is not valid.", problems)
    changed = [name for name in PROTECTED if body[name] != before[name]]
    if changed:
        raise SpecError(
            "invalid_spec",
            "The spec belongs to another episode or version.",
            [f"`{name}` may not be changed." for name in changed],
        )
    if drawable:
        raise SpecError(
            "invalid_spec", "The spec asks for something the theme cannot draw.", drawable
        )


def replace_spec(
    session: Session,
    episode_id: uuid.UUID,
    body: Mapping[str, Any],
    *,
    author: SpecAuthor,
    capability_problems: Sequence[str] = (),
) -> SpecVersion:
    """Store a whole new spec as the next version, after checking it.

    `capability_problems` is what the theme cannot draw in `body`. The caller finds that
    out, because the themes live with the render engine.
    """
    before = current(session, episode_id)
    if before is None:
        raise SpecError("no_spec", "This episode has no spec yet. It is written by the plan.")
    old = dict(before.body)
    _checked(body, old, capability_problems)
    if dict(body) == old:
        return before
    stored = store_spec(session, episode_id, body, author=author)
    pipeline.spec_edited(session, episode_id, old, dict(body))
    return stored


def patched(
    session: Session, episode_id: uuid.UUID, patch: Sequence[Mapping[str, Any]], base_version: int
) -> dict[str, Any]:
    """The current spec with a patch applied, without storing anything.

    The patch was written for `base_version`. If the spec has changed since, it no longer
    says what the owner saw, and it is refused.
    """
    before = current(session, episode_id)
    if before is None:
        raise SpecError("no_spec", "This episode has no spec yet. It is written by the plan.")
    if before.version != base_version:
        raise SpecError(
            "spec_changed",
            f"This change was proposed for version {base_version} of the spec, and the spec "
            f"is now at version {before.version}. Ask for the change again.",
        )
    try:
        result: dict[str, Any] = json_patch.apply(dict(before.body), patch)
    except json_patch.PatchError as error:
        raise SpecError("invalid_patch", "The change cannot be applied.", [str(error)]) from error
    return result
