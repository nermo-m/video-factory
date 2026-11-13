"""Job handlers of the `asset_gen` state (design doc section 4.1, FR-06, FR-30).

* `gen.image` makes one picture and stores it as a new version of its asset, with the
  prompt and what made it. One picture per job, so a plan's image budget is asked before
  each one (section 3.5).
* `gen.clip` turns a picture into a short moving clip. Its adapter, ComfyUI with Wan 2.2,
  is not built yet (VFS-29). Until then the job finishes without a clip and says so, and
  the scene shows its still picture.

A picture that already has a file is kept. Making it again costs the owner's plan an
image, so that only happens when the job says `regenerate`, which is what the owner's
Regenerate does.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from apps.worker.handlers.plan import current_spec
from apps.worker.runner import Handler, JobContext
from packages.adapters.image import ImageAdapter, ImageRequest
from packages.core import assets, limits
from packages.core.db.models import Episode
from packages.core.enums import AssetOrigin, ErrorClass, UsageKind
from packages.core.queue import JobError
from packages.core.storage import StorageAdapter

IMAGE_JOB, CLIP_JOB = "gen.image", "gen.clip"
# All words on screen are drawn by the render engine (section 8), so a picture must not
# carry any of its own.
NO_TEXT = "No text, letters, numbers, captions, logos or watermarks anywhere in the picture."


def full_prompt(prompt: str, note: str | None = None) -> str:
    """The prompt as it is sent: the planned prompt, what the owner asked to be different
    when the picture is made again, and the rule about text."""
    parts = [prompt.replace(NO_TEXT, "").rstrip()]
    if note and note.strip():
        parts.append(f"Asked for by the owner: {note.strip()}")
    parts.append(NO_TEXT)
    return "\n\n".join(parts)


def _asset_id(context: JobContext) -> str:
    asset_id = context.job.input.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id:
        raise JobError(f"A '{context.job.type}' job needs an asset_id.", error_class=ErrorClass.BUG)
    return asset_id


def _episode(session: Session, episode_id: uuid.UUID | None) -> Episode:
    episode = session.get(Episode, episode_id) if episode_id is not None else None
    if episode is None:
        raise JobError("A picture job needs an episode.", error_class=ErrorClass.BUG)
    return episode


def picture_handlers(
    sessions: sessionmaker[Session],
    *,
    storage: StorageAdapter,
    image: Callable[[], ImageAdapter],
) -> dict[str, Handler]:
    """The handlers, for a worker that has a database, a storage and a picture adapter.

    `image` is called for every job, so the adapter is the one of the mode as it is then.
    """

    def gen_image(context: JobContext) -> Mapping[str, Any]:
        asset_id = _asset_id(context)
        with sessions.begin() as session:
            episode = _episode(session, context.job.episode_id)
            spec = current_spec(session, episode)
            # A picture that entered the spec after the asset plan ran gets its row here.
            assets.sync(session, episode, spec)
            picture = next(
                (item for item in assets.resolve(session, episode, spec) if item.id == asset_id),
                None,
            )
            if picture is None:
                raise JobError(f"The spec has no picture '{asset_id}'.", error_class=ErrorClass.BUG)
            if picture.origin != AssetOrigin.GENERATED.value:
                return {
                    "asset_id": asset_id,
                    "made": False,
                    "why": f"This picture is {picture.origin}, so nothing is generated.",
                }
            if picture.file is not None and not context.job.input.get("regenerate"):
                return {
                    "asset_id": asset_id,
                    "made": False,
                    "file": picture.file,
                    "why": "This picture already has a file. Regenerate makes a new one.",
                }
            if not picture.prompt:
                raise JobError(
                    f"The picture '{asset_id}' is to be generated and has no prompt. "
                    "Run the asset plan again.",
                    error_class=ErrorClass.NEEDS_OWNER,
                )
            note = context.job.input.get("note")
            prompt = full_prompt(picture.prompt, note if isinstance(note, str) else None)

        result = image().create(ImageRequest(asset_id=asset_id, prompt=prompt))
        stored = context.output_path / f"{asset_id}.png"
        storage.write_bytes(stored, result.data)

        with sessions.begin() as session:
            episode = _episode(session, context.job.episode_id)
            picture = next(
                item
                for item in assets.resolve(session, episode, current_spec(session, episode))
                if item.id == asset_id
            )
            assert picture.asset is not None  # noqa: S101 - synced above
            version = assets.add_version(
                session,
                picture.asset,
                file_path=stored.as_posix(),
                prompt=prompt,
                model=result.model,
                seed=result.seed,
                width=result.width,
                height=result.height,
                cost_usd=result.cost_usd,
            )
            if not picture.asset.licence:
                # Where the picture came from (section 5.2: every asset has a licence).
                # Its rights stay as the plan marked them, for the owner to review.
                picture.asset.licence = result.licence
            # The picture counts towards the provider's 5 hour and 7 day windows (FR-31).
            limits.record_usage(
                session,
                provider=result.provider,
                model=result.model,
                kind=UsageKind.IMAGE,
                images=1,
                cost_usd=result.cost_usd,
                job_id=context.job.id,
            )
            return {
                "asset_id": asset_id,
                "made": True,
                "file": version.file_path,
                "width": result.width,
                "height": result.height,
                "model": result.model,
                "provider": result.provider.value,
                "latency_ms": result.latency_ms,
            }

    def gen_clip(context: JobContext) -> Mapping[str, Any]:
        return {
            "asset_id": _asset_id(context),
            "scene_id": context.job.input.get("scene_id"),
            "made": False,
            "why": "Clips are not built yet (ComfyUI and Wan 2.2 arrive with VFS-29). "
            "The scene shows its still picture.",
        }

    return {IMAGE_JOB: gen_image, CLIP_JOB: gen_clip}
