"""Tables from design doc section 9, plus the provider tables from section 3.5.

Conventions:

* Every table has id, created_at and updated_at (from Base).
* Nothing is deleted in v1, so every foreign key is ON DELETE RESTRICT.
* Money is exact decimal. Timestamps carry a time zone.
* Fixed value sets are text columns with a CHECK constraint (see packages.core.enums).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.core import enums
from packages.core.db.base import Base, enum_check, enum_type, not_negative

EMPTY_OBJECT = text("'{}'::jsonb")
EMPTY_LIST = text("'[]'::jsonb")
ZERO = Decimal("0")


def _fk(target: str, *, nullable: bool = False, index: bool = True) -> Mapped[Any]:
    return mapped_column(ForeignKey(target, ondelete="RESTRICT"), nullable=nullable, index=index)


class Channel(Base):
    """The channel template: voice, theme, style and house rules."""

    __tablename__ = "channel"
    __table_args__ = (
        CheckConstraint("voice_speed > 0", name="voice_speed_positive"),
        CheckConstraint("target_duration_s > 0", name="target_duration_s_positive"),
    )

    name: Mapped[str] = mapped_column(String(120))
    motto: Mapped[str] = mapped_column(Text, default="", server_default="")
    style_block: Mapped[str] = mapped_column(Text, default="", server_default="")
    voice_id: Mapped[str] = mapped_column(String(64))
    voice_speed: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    theme: Mapped[str] = mapped_column(String(64))
    target_duration_s: Mapped[int] = mapped_column(Integer, default=45, server_default="45")
    pronunciation: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=EMPTY_OBJECT
    )
    banned_topics: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)


class Episode(Base):
    __tablename__ = "episode"
    __table_args__ = (
        enum_check("state", enums.EpisodeState),
        enum_check("stale_from_state", enums.EpisodeState),
        not_negative("total_cost_usd"),
    )

    channel_id: Mapped[uuid.UUID] = _fk("channel.id")
    title: Mapped[str | None] = mapped_column(String(200))
    idea: Mapped[str] = mapped_column(Text)
    state: Mapped[enums.EpisodeState] = mapped_column(
        enum_type(enums.EpisodeState),
        default=enums.EpisodeState.IDEA,
        server_default=enums.EpisodeState.IDEA.value,
        index=True,
    )
    awaiting_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    stale_from_state: Mapped[enums.EpisodeState | None] = mapped_column(
        enum_type(enums.EpisodeState)
    )
    # Scenes an edit of the spec made stale: {"voice": [scene ids], "render": [scene ids]}.
    # Empty when no scene is stale (section 4.2).
    stale_scenes: Mapped[dict[str, list[str]]] = mapped_column(
        JSONB, default=dict, server_default=EMPTY_OBJECT
    )
    # Points back at spec_version, which points at episode: created after both tables exist.
    current_spec_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "spec_version.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_episode_current_spec_id_spec_version",
        )
    )
    total_cost_usd: Mapped[Decimal] = mapped_column(default=ZERO, server_default="0")


class SpecVersion(Base):
    """One immutable version of an episode spec, authored or resolved."""

    __tablename__ = "spec_version"
    __table_args__ = (
        UniqueConstraint("episode_id", "version"),
        enum_check("kind", enums.SpecKind),
        enum_check("author", enums.SpecAuthor),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    episode_id: Mapped[uuid.UUID] = _fk("episode.id")
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[enums.SpecKind] = mapped_column(enum_type(enums.SpecKind))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    author: Mapped[enums.SpecAuthor] = mapped_column(enum_type(enums.SpecAuthor))
    skill_version: Mapped[str | None] = mapped_column(String(32))
    parent_id: Mapped[uuid.UUID | None] = _fk("spec_version.id", nullable=True)


class Claim(Base):
    """A factual claim with the source passage that supports it (FR-02)."""

    __tablename__ = "claim"
    __table_args__ = (
        # A claim is kept only if the passage supporting it was actually retrieved.
        CheckConstraint("length(btrim(passage)) > 0", name="passage_not_empty"),
    )

    episode_id: Mapped[uuid.UUID] = _fk("episode.id")
    text: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(200))
    source_date: Mapped[date | None] = mapped_column(Date)
    passage: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column()


class Asset(Base):
    """An image, clip, sound or sprite. Library assets have no episode."""

    __tablename__ = "asset"
    __table_args__ = (
        UniqueConstraint("channel_id", "key"),
        enum_check("kind", enums.AssetKind),
        enum_check("origin", enums.AssetOrigin),
        enum_check("rights_status", enums.RightsStatus),
    )

    channel_id: Mapped[uuid.UUID] = _fk("channel.id", index=False)
    episode_id: Mapped[uuid.UUID | None] = _fk("episode.id", nullable=True)
    key: Mapped[str] = mapped_column(String(120))
    kind: Mapped[enums.AssetKind] = mapped_column(enum_type(enums.AssetKind))
    origin: Mapped[enums.AssetOrigin] = mapped_column(enum_type(enums.AssetOrigin))
    licence: Mapped[str | None] = mapped_column(String(120))
    contains_third_party_ip: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Fail closed: an asset blocks Finish and export until someone clears it (FR-08).
    rights_status: Mapped[enums.RightsStatus] = mapped_column(
        enum_type(enums.RightsStatus),
        default=enums.RightsStatus.NEEDS_REVIEW,
        server_default=enums.RightsStatus.NEEDS_REVIEW.value,
    )
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)


class AssetVersion(Base):
    __tablename__ = "asset_version"
    __table_args__ = (
        # At most one active version per asset, enforced by the database.
        Index(
            "uq_asset_version_one_active",
            "asset_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        not_negative("cost_usd"),
    )

    asset_id: Mapped[uuid.UUID] = _fk("asset.id")
    file_path: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(120))
    seed: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    cost_usd: Mapped[Decimal] = mapped_column(default=ZERO, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Job(Base):
    """One unit of work in the Postgres-backed queue (D8, section 4.3)."""

    __tablename__ = "job"
    __table_args__ = (
        Index("ix_job_status_tag_run_after", "status", "tag", "run_after"),
        enum_check("tag", enums.JobTag),
        enum_check("status", enums.JobStatus),
        enum_check("error_class", enums.ErrorClass),
        not_negative("attempts"),
        not_negative("cost_usd"),
    )

    episode_id: Mapped[uuid.UUID | None] = _fk("episode.id", nullable=True)
    type: Mapped[str] = mapped_column(String(64))
    tag: Mapped[enums.JobTag] = mapped_column(enum_type(enums.JobTag))
    status: Mapped[enums.JobStatus] = mapped_column(
        enum_type(enums.JobStatus),
        default=enums.JobStatus.QUEUED,
        server_default=enums.JobStatus.QUEUED.value,
    )
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_class: Mapped[enums.ErrorClass | None] = mapped_column(enum_type(enums.ErrorClass))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    heartbeat_at: Mapped[datetime | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    cost_usd: Mapped[Decimal] = mapped_column(default=ZERO, server_default="0")


class Render(Base):
    __tablename__ = "render"
    __table_args__ = (enum_check("kind", enums.RenderKind),)

    episode_id: Mapped[uuid.UUID] = _fk("episode.id")
    resolved_spec_id: Mapped[uuid.UUID] = _fk("spec_version.id")
    kind: Mapped[enums.RenderKind] = mapped_column(enum_type(enums.RenderKind))
    file_path: Mapped[str | None] = mapped_column(Text)
    scene_files: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)
    contact_sheet_path: Mapped[str | None] = mapped_column(Text)
    qc_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    duration_s: Mapped[float | None] = mapped_column(Float)


class Review(Base):
    """The owner's verdict on one render (section 11.4)."""

    __tablename__ = "review"
    __table_args__ = (enum_check("verdict", enums.ReviewVerdict),)

    episode_id: Mapped[uuid.UUID] = _fk("episode.id")
    render_id: Mapped[uuid.UUID] = _fk("render.id")
    verdict: Mapped[enums.ReviewVerdict] = mapped_column(enum_type(enums.ReviewVerdict))
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    resulting_spec_id: Mapped[uuid.UUID | None] = _fk("spec_version.id", nullable=True)


class AgentRun(Base):
    __tablename__ = "agent_run"
    __table_args__ = (
        enum_check("agent", enums.AgentName),
        enum_check("status", enums.AgentRunStatus),
        not_negative("rounds"),
        not_negative("tool_calls"),
        not_negative("cost_usd"),
    )

    episode_id: Mapped[uuid.UUID] = _fk("episode.id")
    agent: Mapped[enums.AgentName] = mapped_column(enum_type(enums.AgentName))
    status: Mapped[enums.AgentRunStatus] = mapped_column(
        enum_type(enums.AgentRunStatus),
        default=enums.AgentRunStatus.RUNNING,
        server_default=enums.AgentRunStatus.RUNNING.value,
    )
    rounds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(default=ZERO, server_default="0")
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column()


class AgentStep(Base):
    """One tool call in an agent run, stored so the trace can be read back (FR-21)."""

    __tablename__ = "agent_step"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "index"),
        not_negative("tokens"),
        not_negative("cost_usd"),
        not_negative("duration_ms"),
    )

    agent_run_id: Mapped[uuid.UUID] = _fk("agent_run.id", index=False)
    index: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=EMPTY_OBJECT
    )
    result_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    accepted: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(default=ZERO, server_default="0")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ProviderUsage(Base):
    """One counted use of a provider, for the rolling 5 hour and 7 day windows (3.5)."""

    __tablename__ = "provider_usage"
    __table_args__ = (
        Index("ix_provider_usage_provider_created_at", "provider", "created_at"),
        enum_check("provider", enums.Provider),
        enum_check("kind", enums.UsageKind),
        enum_check("billing", enums.Billing),
        not_negative("input_tokens"),
        not_negative("output_tokens"),
        not_negative("images"),
        not_negative("cost_usd"),
    )

    provider: Mapped[enums.Provider] = mapped_column(enum_type(enums.Provider))
    model: Mapped[str] = mapped_column(String(120))
    kind: Mapped[enums.UsageKind] = mapped_column(enum_type(enums.UsageKind))
    job_id: Mapped[uuid.UUID | None] = _fk("job.id", nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    images: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    billing: Mapped[enums.Billing] = mapped_column(enum_type(enums.Billing))
    cost_usd: Mapped[Decimal] = mapped_column(default=ZERO, server_default="0")


class ProviderStatus(Base):
    """Where one provider stands: ok, near budget, paused or limited (3.5)."""

    __tablename__ = "provider_status"
    __table_args__ = (
        UniqueConstraint("provider"),
        enum_check("provider", enums.Provider),
        enum_check("state", enums.ProviderState),
        enum_check("source", enums.StatusSource),
    )

    provider: Mapped[enums.Provider] = mapped_column(enum_type(enums.Provider))
    state: Mapped[enums.ProviderState] = mapped_column(
        enum_type(enums.ProviderState),
        default=enums.ProviderState.OK,
        server_default=enums.ProviderState.OK.value,
    )
    limited_until: Mapped[datetime | None] = mapped_column()
    source: Mapped[enums.StatusSource] = mapped_column(enum_type(enums.StatusSource))
    last_checked_at: Mapped[datetime | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(Text)


class ModelCall(Base):
    """One call to a language or image model, with its cost and billing type (FR-17, FR-29)."""

    __tablename__ = "model_call"
    __table_args__ = (
        enum_check("provider", enums.Provider),
        enum_check("billing", enums.Billing),
        not_negative("input_tokens"),
        not_negative("output_tokens"),
        not_negative("cost_usd"),
        not_negative("latency_ms"),
    )

    job_id: Mapped[uuid.UUID | None] = _fk("job.id", nullable=True)
    provider: Mapped[enums.Provider] = mapped_column(enum_type(enums.Provider))
    model: Mapped[str] = mapped_column(String(120))
    billing: Mapped[enums.Billing] = mapped_column(enum_type(enums.Billing))
    skill: Mapped[str | None] = mapped_column(String(64))
    skill_version: Mapped[str | None] = mapped_column(String(32))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(default=ZERO, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Setting(Base):
    """Non-secret settings only. Secrets come from environment variables (NFR-01)."""

    __tablename__ = "setting"
    __table_args__ = (UniqueConstraint("key"),)

    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[Any] = mapped_column(JSONB)
