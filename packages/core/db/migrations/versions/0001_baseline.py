"""Baseline: every table from design doc sections 9 and 3.5.

Fixed value sets are text columns with CHECK constraints, so adding a value later is an
ordinary migration. Every foreign key is ON DELETE RESTRICT: nothing is deleted in v1.

Revision ID: 0001
Revises:
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("motto", sa.Text(), server_default="", nullable=False),
        sa.Column("style_block", sa.Text(), server_default="", nullable=False),
        sa.Column("voice_id", sa.String(length=64), nullable=False),
        sa.Column("voice_speed", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("theme", sa.String(length=64), nullable=False),
        sa.Column("target_duration_s", sa.Integer(), server_default="45", nullable=False),
        sa.Column(
            "pronunciation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "banned_topics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_duration_s > 0", name=op.f("ck_channel_target_duration_s_positive")
        ),
        sa.CheckConstraint("voice_speed > 0", name=op.f("ck_channel_voice_speed_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel")),
    )
    op.create_table(
        "provider_status",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="ok", nullable=False),
        sa.Column("limited_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('demo', 'claude_plan', 'chatgpt_plan', 'anthropic_api', 'openai_api')",
            name=op.f("ck_provider_status_provider_valid"),
        ),
        sa.CheckConstraint(
            "source IN ('tool', 'app')", name=op.f("ck_provider_status_source_valid")
        ),
        sa.CheckConstraint(
            "state IN ('ok', 'near_budget', 'paused_by_budget', 'limited')",
            name=op.f("ck_provider_status_state_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_status")),
        sa.UniqueConstraint("provider", name=op.f("uq_provider_status_provider")),
    )
    op.create_table(
        "setting",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_setting")),
        sa.UniqueConstraint("key", name=op.f("uq_setting_key")),
    )
    op.create_table(
        "episode",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("idea", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="idea", nullable=False),
        sa.Column(
            "awaiting_approval", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("stale_from_state", sa.String(length=32), nullable=True),
        sa.Column("current_spec_id", sa.Uuid(), nullable=True),
        sa.Column(
            "total_cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stale_from_state IN ('idea', 'brief', 'research', 'script', 'direction', 'asset_plan', 'asset_gen', 'voice', 'render', 'qc', 'critique', 'package', 'export', 'done')",
            name=op.f("ck_episode_stale_from_state_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('idea', 'brief', 'research', 'script', 'direction', 'asset_plan', 'asset_gen', 'voice', 'render', 'qc', 'critique', 'package', 'export', 'done')",
            name=op.f("ck_episode_state_valid"),
        ),
        sa.CheckConstraint(
            "total_cost_usd >= 0", name=op.f("ck_episode_total_cost_usd_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channel.id"],
            name=op.f("fk_episode_channel_id_channel"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episode")),
    )
    op.create_index(op.f("ix_episode_channel_id"), "episode", ["channel_id"], unique=False)
    op.create_index(op.f("ix_episode_state"), "episode", ["state"], unique=False)
    op.create_table(
        "agent_run",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="running", nullable=False),
        sa.Column("rounds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "agent IN ('critic', 'producer')", name=op.f("ck_agent_run_agent_valid")
        ),
        sa.CheckConstraint(
            "status IN ('running', 'finished', 'limit_reached', 'failed', 'stopped_by_owner')",
            name=op.f("ck_agent_run_status_valid"),
        ),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_agent_run_cost_usd_not_negative")),
        sa.CheckConstraint("rounds >= 0", name=op.f("ck_agent_run_rounds_not_negative")),
        sa.CheckConstraint("tool_calls >= 0", name=op.f("ck_agent_run_tool_calls_not_negative")),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episode.id"],
            name=op.f("fk_agent_run_episode_id_episode"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_run")),
    )
    op.create_index(op.f("ix_agent_run_episode_id"), "agent_run", ["episode_id"], unique=False)
    op.create_table(
        "asset",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=True),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("licence", sa.String(length=120), nullable=True),
        sa.Column(
            "contains_third_party_ip", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "rights_status", sa.String(length=32), server_default="needs_review", nullable=False
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('image', 'clip', 'audio', 'sprite')", name=op.f("ck_asset_kind_valid")
        ),
        sa.CheckConstraint(
            "origin IN ('generated', 'uploaded', 'library')", name=op.f("ck_asset_origin_valid")
        ),
        sa.CheckConstraint(
            "rights_status IN ('cleared', 'needs_review', 'blocked')",
            name=op.f("ck_asset_rights_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channel.id"],
            name=op.f("fk_asset_channel_id_channel"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episode.id"],
            name=op.f("fk_asset_episode_id_episode"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset")),
        sa.UniqueConstraint("channel_id", "key", name=op.f("uq_asset_channel_id_key")),
    )
    op.create_index(op.f("ix_asset_episode_id"), "asset", ["episode_id"], unique=False)
    op.create_table(
        "claim",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("passage", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(btrim(passage)) > 0", name=op.f("ck_claim_passage_not_empty")),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episode.id"],
            name=op.f("fk_claim_episode_id_episode"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim")),
    )
    op.create_index(op.f("ix_claim_episode_id"), "claim", ["episode_id"], unique=False)
    op.create_table(
        "job",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("tag", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_class", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "error_class IN ('retryable', 'invalid_output', 'needs_owner', 'bug', 'plan_limit')",
            name=op.f("ck_job_error_class_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_job_status_valid"),
        ),
        sa.CheckConstraint("tag IN ('cpu', 'gpu')", name=op.f("ck_job_tag_valid")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_job_attempts_not_negative")),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_job_cost_usd_not_negative")),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episode.id"],
            name=op.f("fk_job_episode_id_episode"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job")),
    )
    op.create_index(op.f("ix_job_episode_id"), "job", ["episode_id"], unique=False)
    op.create_index(
        "ix_job_status_tag_run_after", "job", ["status", "tag", "run_after"], unique=False
    )
    op.create_table(
        "spec_version",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("author", sa.String(length=32), nullable=False),
        sa.Column("skill_version", sa.String(length=32), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "author IN ('model', 'owner')", name=op.f("ck_spec_version_author_valid")
        ),
        sa.CheckConstraint(
            "kind IN ('authored', 'resolved')", name=op.f("ck_spec_version_kind_valid")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_spec_version_version_positive")),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episode.id"],
            name=op.f("fk_spec_version_episode_id_episode"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["spec_version.id"],
            name=op.f("fk_spec_version_parent_id_spec_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spec_version")),
        sa.UniqueConstraint(
            "episode_id", "version", name=op.f("uq_spec_version_episode_id_version")
        ),
    )
    op.create_index(
        op.f("ix_spec_version_episode_id"), "spec_version", ["episode_id"], unique=False
    )
    op.create_index(op.f("ix_spec_version_parent_id"), "spec_version", ["parent_id"], unique=False)
    # episode and spec_version point at each other, so this key is added once both exist.
    op.create_foreign_key(
        "fk_episode_current_spec_id_spec_version",
        "episode",
        "spec_version",
        ["current_spec_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "agent_step",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column(
            "arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result_summary", sa.Text(), server_default="", nullable=False),
        sa.Column("accepted", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_agent_step_cost_usd_not_negative")),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_agent_step_duration_ms_not_negative")),
        sa.CheckConstraint("tokens >= 0", name=op.f("ck_agent_step_tokens_not_negative")),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_run.id"],
            name=op.f("fk_agent_step_agent_run_id_agent_run"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_step")),
        sa.UniqueConstraint("agent_run_id", "index", name=op.f("uq_agent_step_agent_run_id_index")),
    )
    op.create_table(
        "asset_version",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_asset_version_cost_usd_not_negative")),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset.id"],
            name=op.f("fk_asset_version_asset_id_asset"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_version")),
    )
    op.create_index(op.f("ix_asset_version_asset_id"), "asset_version", ["asset_id"], unique=False)
    op.create_index(
        "uq_asset_version_one_active",
        "asset_version",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "model_call",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("billing", sa.String(length=32), nullable=False),
        sa.Column("skill", sa.String(length=64), nullable=True),
        sa.Column("skill_version", sa.String(length=32), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "billing IN ('demo', 'plan', 'api')", name=op.f("ck_model_call_billing_valid")
        ),
        sa.CheckConstraint(
            "provider IN ('demo', 'claude_plan', 'chatgpt_plan', 'anthropic_api', 'openai_api')",
            name=op.f("ck_model_call_provider_valid"),
        ),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_model_call_cost_usd_not_negative")),
        sa.CheckConstraint(
            "input_tokens >= 0", name=op.f("ck_model_call_input_tokens_not_negative")
        ),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_model_call_latency_ms_not_negative")),
        sa.CheckConstraint(
            "output_tokens >= 0", name=op.f("ck_model_call_output_tokens_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_model_call_job_id_job"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_call")),
    )
    op.create_index(op.f("ix_model_call_job_id"), "model_call", ["job_id"], unique=False)
    op.create_table(
        "provider_usage",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("images", sa.Integer(), server_default="0", nullable=False),
        sa.Column("billing", sa.String(length=32), nullable=False),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "billing IN ('demo', 'plan', 'api')", name=op.f("ck_provider_usage_billing_valid")
        ),
        sa.CheckConstraint("kind IN ('text', 'image')", name=op.f("ck_provider_usage_kind_valid")),
        sa.CheckConstraint(
            "provider IN ('demo', 'claude_plan', 'chatgpt_plan', 'anthropic_api', 'openai_api')",
            name=op.f("ck_provider_usage_provider_valid"),
        ),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_provider_usage_cost_usd_not_negative")),
        sa.CheckConstraint("images >= 0", name=op.f("ck_provider_usage_images_not_negative")),
        sa.CheckConstraint(
            "input_tokens >= 0", name=op.f("ck_provider_usage_input_tokens_not_negative")
        ),
        sa.CheckConstraint(
            "output_tokens >= 0", name=op.f("ck_provider_usage_output_tokens_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_provider_usage_job_id_job"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_usage")),
    )
    op.create_index(op.f("ix_provider_usage_job_id"), "provider_usage", ["job_id"], unique=False)
    op.create_index(
        "ix_provider_usage_provider_created_at",
        "provider_usage",
        ["provider", "created_at"],
        unique=False,
    )
    op.create_table(
        "render",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("resolved_spec_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column(
            "scene_files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("contact_sheet_path", sa.Text(), nullable=True),
        sa.Column("qc_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('preview', 'draft', 'final')", name=op.f("ck_render_kind_valid")
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episode.id"],
            name=op.f("fk_render_episode_id_episode"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_spec_id"],
            ["spec_version.id"],
            name=op.f("fk_render_resolved_spec_id_spec_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_render")),
    )
    op.create_index(op.f("ix_render_episode_id"), "render", ["episode_id"], unique=False)
    op.create_index(
        op.f("ix_render_resolved_spec_id"), "render", ["resolved_spec_id"], unique=False
    )
    op.create_table(
        "review",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("render_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), server_default="", nullable=False),
        sa.Column("resulting_spec_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "verdict IN ('finished', 'adjust', 'remake')", name=op.f("ck_review_verdict_valid")
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episode.id"],
            name=op.f("fk_review_episode_id_episode"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["render_id"],
            ["render.id"],
            name=op.f("fk_review_render_id_render"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resulting_spec_id"],
            ["spec_version.id"],
            name=op.f("fk_review_resulting_spec_id_spec_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review")),
    )
    op.create_index(op.f("ix_review_episode_id"), "review", ["episode_id"], unique=False)
    op.create_index(op.f("ix_review_render_id"), "review", ["render_id"], unique=False)
    op.create_index(
        op.f("ix_review_resulting_spec_id"), "review", ["resulting_spec_id"], unique=False
    )


def downgrade() -> None:
    op.drop_constraint("fk_episode_current_spec_id_spec_version", "episode", type_="foreignkey")
    op.drop_index(op.f("ix_review_resulting_spec_id"), table_name="review")
    op.drop_index(op.f("ix_review_render_id"), table_name="review")
    op.drop_index(op.f("ix_review_episode_id"), table_name="review")
    op.drop_table("review")
    op.drop_index(op.f("ix_render_resolved_spec_id"), table_name="render")
    op.drop_index(op.f("ix_render_episode_id"), table_name="render")
    op.drop_table("render")
    op.drop_index("ix_provider_usage_provider_created_at", table_name="provider_usage")
    op.drop_index(op.f("ix_provider_usage_job_id"), table_name="provider_usage")
    op.drop_table("provider_usage")
    op.drop_index(op.f("ix_model_call_job_id"), table_name="model_call")
    op.drop_table("model_call")
    op.drop_index(
        "uq_asset_version_one_active",
        table_name="asset_version",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_index(op.f("ix_asset_version_asset_id"), table_name="asset_version")
    op.drop_table("asset_version")
    op.drop_table("agent_step")
    op.drop_index(op.f("ix_spec_version_parent_id"), table_name="spec_version")
    op.drop_index(op.f("ix_spec_version_episode_id"), table_name="spec_version")
    op.drop_table("spec_version")
    op.drop_index("ix_job_status_tag_run_after", table_name="job")
    op.drop_index(op.f("ix_job_episode_id"), table_name="job")
    op.drop_table("job")
    op.drop_index(op.f("ix_claim_episode_id"), table_name="claim")
    op.drop_table("claim")
    op.drop_index(op.f("ix_asset_episode_id"), table_name="asset")
    op.drop_table("asset")
    op.drop_index(op.f("ix_agent_run_episode_id"), table_name="agent_run")
    op.drop_table("agent_run")
    op.drop_index(op.f("ix_episode_state"), table_name="episode")
    op.drop_index(op.f("ix_episode_channel_id"), table_name="episode")
    op.drop_table("episode")
    op.drop_table("setting")
    op.drop_table("provider_status")
    op.drop_table("channel")
