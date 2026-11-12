"""An episode's pictures as stored assets (design doc sections 5 and 9, FR-05, FR-06, FR-08).

The spec names the pictures an episode shows. The asset manifest, written by the `assets`
skill, says where each one comes from: generated, uploaded, or reused from the library.
This module turns that into rows:

* A **library** asset belongs to the channel and to no episode. The pictures bundled with
  the sample episode are the first library assets.
* A **generated** or **uploaded** asset belongs to one episode. Two episodes may both name
  a picture `a_harbour`, so its key carries the episode.
* Every file an asset ever had is an `asset_version` with its prompt, model, seed and
  cost. Exactly one version is active, and that is the one a render uses.

`resolve` reads what an episode's pictures are right now. A render may only start when
every picture has an active version (FR-05), and Finish and export only when every
picture's rights are cleared (FR-08).

The functions take a Session and never commit.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from packages.core.db.models import Asset, AssetVersion, Channel, Episode, Job
from packages.core.enums import AssetKind, AssetOrigin, JobStatus, RightsStatus
from packages.core.storage import StorageAdapter

MANIFEST_JOB = "plan.assets"
_SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "lighthouse_keeper"


@dataclass(frozen=True)
class Picture:
    """One picture of an episode, as it is right now."""

    id: str
    kind: str
    origin: str
    used_in: tuple[str, ...]
    becomes_clip: bool
    prompt: str | None
    filename: str | None
    asset: Asset | None
    version: AssetVersion | None

    @property
    def file(self) -> str | None:
        return self.version.file_path if self.version is not None else None


@dataclass(frozen=True)
class StoredFile:
    file: str
    licence: str | None


def episode_key(episode_id: uuid.UUID, asset_id: str) -> str:
    """The key of an episode's own asset. Library assets use the asset id alone."""
    return f"{episode_id}:{asset_id}"


# --- the library ---------------------------------------------------------------------------


def bundled_pictures() -> list[dict[str, Any]]:
    """The assets of the sample episode that have a bundled file: the first library."""
    spec = json.loads((_SAMPLE / "episode_spec.json").read_text(encoding="utf-8"))
    return [
        asset
        for asset in spec["assets"]
        if asset["origin"] == "library" and (_SAMPLE / "assets" / f"{asset['id']}.png").is_file()
    ]


def store_bundled(storage: StorageAdapter) -> dict[str, StoredFile]:
    """Copy the bundled pictures into the storage, once. Returns where each one is."""
    stored: dict[str, StoredFile] = {}
    for asset in bundled_pictures():
        path = f"library/{asset['id']}/v1.png"
        if not storage.exists(path):
            storage.write_bytes(path, (_SAMPLE / "assets" / f"{asset['id']}.png").read_bytes())
        stored[asset["id"]] = StoredFile(path, asset.get("licence"))
    return stored


def ensure_library(session: Session, storage: StorageAdapter, channel_id: uuid.UUID) -> None:
    """Make sure the channel's library holds the bundled pictures. Safe to call again."""
    files = store_bundled(storage)
    # Two episodes of one channel may plan their pictures at the same moment.
    session.get(Channel, channel_id, with_for_update=True)
    have = set(
        session.scalars(
            select(Asset.key).where(Asset.channel_id == channel_id, Asset.episode_id.is_(None))
        )
    )
    for bundled in bundled_pictures():
        if bundled["id"] in have:
            continue
        asset = Asset(
            channel_id=channel_id,
            episode_id=None,
            key=bundled["id"],
            kind=AssetKind(bundled["kind"]),
            origin=AssetOrigin.LIBRARY,
            licence=bundled.get("licence"),
            contains_third_party_ip=bundled["contains_third_party_ip"],
            rights_status=RightsStatus(bundled["rights_status"]),
            tags=list(bundled.get("tags", [])),
        )
        session.add(asset)
        session.flush()
        add_version(session, asset, file_path=files[bundled["id"]].file)


# --- an episode's own assets ---------------------------------------------------------------


def manifest_of(session: Session, episode_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """The entries of the episode's newest asset manifest, by asset id. Empty without one."""
    output = session.scalar(
        select(Job.output)
        .where(
            Job.episode_id == episode_id,
            Job.type == MANIFEST_JOB,
            Job.status == JobStatus.SUCCEEDED,
        )
        .order_by(Job.finished_at.desc(), Job.created_at.desc())
        .limit(1)
    )
    document = output.get("document") if isinstance(output, dict) else None
    entries = document.get("assets") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return {}
    return {entry["id"]: entry for entry in entries if isinstance(entry, dict) and "id" in entry}


def _entries(
    spec: Mapping[str, Any], manifest: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """What is known about each picture of the spec: the manifest's word where it has one,
    the spec's own otherwise."""
    used: dict[str, list[str]] = {}
    clips: set[str] = set()
    for scene in spec["scenes"]:
        visual = scene.get("visual")
        if visual:
            used.setdefault(visual["asset_id"], []).append(scene["id"])
            if visual.get("clip"):
                clips.add(visual["asset_id"])
    entries = []
    for asset in spec["assets"]:
        entry = {**asset, **manifest.get(asset["id"], {})}
        entry["used_in"] = used.get(asset["id"], [])
        entry["becomes_clip"] = asset["id"] in clips
        entries.append(entry)
    return entries


def sync(
    session: Session,
    episode: Episode,
    spec: Mapping[str, Any],
    manifest: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Asset]:
    """Make sure every generated or uploaded picture of the spec has its asset row.

    Returns the rows it added. Nothing is changed or deleted: a picture that left the spec
    keeps its row and its files, and rights the owner set stay as they are.
    """
    known = manifest if manifest is not None else manifest_of(session, episode.id)
    have = set(session.scalars(select(Asset.key).where(Asset.episode_id == episode.id)))
    added = []
    for entry in _entries(spec, known):
        key = episode_key(episode.id, entry["id"])
        if entry["origin"] == AssetOrigin.LIBRARY.value or key in have:
            continue
        asset = Asset(
            channel_id=episode.channel_id,
            episode_id=episode.id,
            key=key,
            kind=AssetKind(entry["kind"]),
            origin=AssetOrigin(entry["origin"]),
            licence=entry.get("licence"),
            contains_third_party_ip=bool(entry.get("contains_third_party_ip", False)),
            rights_status=RightsStatus(entry.get("rights_status", RightsStatus.NEEDS_REVIEW)),
            tags=list(entry.get("tags", [])),
        )
        session.add(asset)
        added.append(asset)
    session.flush()
    return added


def add_version(
    session: Session,
    asset: Asset,
    *,
    file_path: str,
    prompt: str | None = None,
    model: str | None = None,
    seed: int | None = None,
    width: int | None = None,
    height: int | None = None,
    duration_s: float | None = None,
    cost_usd: Decimal = Decimal("0"),
) -> AssetVersion:
    """Store a new file of an asset and make it the active one (FR-06). Earlier versions
    are kept."""
    session.execute(
        update(AssetVersion)
        .where(AssetVersion.asset_id == asset.id, AssetVersion.is_active)
        .values(is_active=False)
    )
    version = AssetVersion(
        asset_id=asset.id,
        file_path=file_path,
        prompt=prompt,
        model=model,
        seed=seed,
        width=width,
        height=height,
        duration_s=duration_s,
        cost_usd=cost_usd,
        is_active=True,
    )
    session.add(version)
    session.flush()
    return version


def activate(session: Session, version: AssetVersion) -> None:
    """Make an earlier version the active one again."""
    session.execute(
        update(AssetVersion)
        .where(AssetVersion.asset_id == version.asset_id, AssetVersion.is_active)
        .values(is_active=False)
    )
    # By id, so it also works for a version that was read in another session.
    session.execute(
        update(AssetVersion).where(AssetVersion.id == version.id).values(is_active=True)
    )


def versions(session: Session, asset: Asset) -> list[AssetVersion]:
    """Every version of an asset, oldest first."""
    return list(
        session.scalars(
            select(AssetVersion)
            .where(AssetVersion.asset_id == asset.id)
            .order_by(AssetVersion.created_at, AssetVersion.id)
        )
    )


# --- reading -------------------------------------------------------------------------------


def resolve(
    session: Session,
    episode: Episode,
    spec: Mapping[str, Any],
    manifest: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Picture]:
    """Every picture of the spec with its asset row and active version, where it has them."""
    known = manifest if manifest is not None else manifest_of(session, episode.id)
    rows = {
        (asset.episode_id, asset.key): asset
        for asset in session.scalars(
            select(Asset).where(
                Asset.channel_id == episode.channel_id,
                Asset.episode_id.is_(None) | (Asset.episode_id == episode.id),
            )
        )
    }
    active = {
        version.asset_id: version
        for version in session.scalars(
            select(AssetVersion).where(
                AssetVersion.is_active, AssetVersion.asset_id.in_([row.id for row in rows.values()])
            )
        )
    }
    pictures = []
    for entry in _entries(spec, known):
        if entry["origin"] == AssetOrigin.LIBRARY.value:
            asset = rows.get((None, entry.get("library_key") or entry["id"]))
        else:
            asset = rows.get((episode.id, episode_key(episode.id, entry["id"])))
        pictures.append(
            Picture(
                id=entry["id"],
                kind=entry["kind"],
                origin=entry["origin"],
                used_in=tuple(entry["used_in"]),
                becomes_clip=entry["becomes_clip"],
                prompt=entry.get("prompt"),
                filename=entry.get("filename"),
                asset=asset,
                version=active.get(asset.id) if asset is not None else None,
            )
        )
    return pictures


def files(pictures: list[Picture]) -> tuple[dict[str, StoredFile], list[Picture]]:
    """The stored file of every resolved picture, and the pictures that have none (FR-05)."""
    stored: dict[str, StoredFile] = {}
    unresolved: list[Picture] = []
    for picture in pictures:
        if picture.asset is None or picture.file is None:
            unresolved.append(picture)
        else:
            stored[picture.id] = StoredFile(picture.file, picture.asset.licence)
    return stored, unresolved


_WHY_UNRESOLVED = {
    AssetOrigin.GENERATED.value: "has not been generated yet",
    AssetOrigin.UPLOADED.value: "waits for your upload",
    AssetOrigin.LIBRARY.value: "is not in the library",
}


def unresolved_text(unresolved: list[Picture]) -> str:
    """Why a render cannot start, in words for the owner."""
    listed = "; ".join(
        f"{picture.id} {_WHY_UNRESOLVED.get(picture.origin, 'has no file')}"
        for picture in unresolved
    )
    return (
        f"The video cannot be rendered while a picture is missing: {listed}. "
        "Run the pictures step again, or upload the missing pictures."
    )


def rights_problems(pictures: list[Picture]) -> list[str]:
    """What stops Finish and export (FR-08): every picture whose rights are not cleared."""
    problems = []
    for picture in pictures:
        if picture.asset is None:
            problems.append(f"{picture.id} has no asset yet, so its rights are unknown.")
        elif picture.asset.rights_status is RightsStatus.BLOCKED:
            problems.append(f"{picture.id} is blocked: its rights do not allow using it.")
        elif picture.asset.rights_status is not RightsStatus.CLEARED:
            problems.append(f"{picture.id} needs its rights reviewed before it can be published.")
        elif picture.asset.contains_third_party_ip:
            problems.append(
                f"{picture.id} is marked as containing someone else's work. Replace it."
            )
    return problems
