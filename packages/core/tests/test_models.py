"""Unit tests for the database models (design doc sections 9 and 3.5). No database needed."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

import pytest
from sqlalchemy import DateTime, Numeric, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB

from packages.core import enums
from packages.core.db import Base, models

SECTION_9_TABLES = {
    "channel",
    "episode",
    "spec_version",
    "claim",
    "asset",
    "asset_version",
    "job",
    "render",
    "review",
    "agent_run",
    "agent_step",
    "provider_usage",
    "provider_status",
    "model_call",
    "setting",
}


def test_section9_every_table_is_modelled() -> None:
    assert set(Base.metadata.tables) == SECTION_9_TABLES


@pytest.mark.parametrize("table_name", sorted(SECTION_9_TABLES))
def test_section9_every_table_has_id_created_at_updated_at(table_name: str) -> None:
    table = Base.metadata.tables[table_name]

    assert isinstance(table.c.id.type, Uuid)
    assert table.c.id.primary_key
    assert table.c.id.server_default is not None
    for name in ("created_at", "updated_at"):
        column = table.c[name]
        assert isinstance(column.type, DateTime)
        assert column.type.timezone is True, f"{table_name}.{name} must carry a time zone"
        assert not column.nullable
        assert column.server_default is not None


def test_section9_listed_indexes_are_declared() -> None:
    tables = Base.metadata.tables

    def index_columns(table_name: str) -> dict[tuple[str, ...], bool]:
        return {
            tuple(column.name for column in index.columns): bool(index.unique)
            for index in tables[table_name].indexes
        }

    def unique_constraints(table_name: str) -> set[tuple[str, ...]]:
        return {
            tuple(column.name for column in constraint.columns)
            for constraint in tables[table_name].constraints
            if isinstance(constraint, UniqueConstraint)
        }

    assert ("status", "tag", "run_after") in index_columns("job")
    assert ("state",) in index_columns("episode")
    assert ("channel_id", "key") in unique_constraints("asset")
    assert ("episode_id", "version") in unique_constraints("spec_version")


def test_money_is_stored_as_exact_decimal_never_float() -> None:
    money_columns = [
        column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.endswith("cost_usd")
    ]

    assert {column.table.name for column in money_columns} == {
        "episode",
        "asset_version",
        "job",
        "agent_run",
        "agent_step",
        "provider_usage",
        "model_call",
    }
    for column in money_columns:
        assert isinstance(column.type, Numeric)
        assert column.type.asdecimal is True
        assert column.type.scale == 6


def test_json_documents_use_jsonb() -> None:
    expected = {
        ("channel", "pronunciation"),
        ("channel", "banned_topics"),
        ("spec_version", "body"),
        ("asset", "tags"),
        ("job", "input"),
        ("job", "output"),
        ("render", "scene_files"),
        ("render", "qc_report"),
        ("agent_run", "report"),
        ("agent_step", "arguments"),
        ("setting", "value"),
    }

    found = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, JSONB)
    }

    assert found == expected


def test_enum_values_match_the_design_document() -> None:
    def values(enum: type[StrEnum]) -> list[str]:
        return [member.value for member in enum]

    assert values(enums.EpisodeState) == [
        "idea",
        "brief",
        "research",
        "script",
        "direction",
        "asset_plan",
        "asset_gen",
        "voice",
        "render",
        "qc",
        "critique",
        "package",
        "export",
        "done",
    ]
    assert values(enums.JobStatus) == ["queued", "running", "succeeded", "failed", "cancelled"]
    assert values(enums.JobTag) == ["cpu", "gpu"]
    assert values(enums.ErrorClass) == [
        "retryable",
        "invalid_output",
        "needs_owner",
        "bug",
        "plan_limit",
    ]
    assert values(enums.SpecKind) == ["authored", "resolved"]
    assert values(enums.SpecAuthor) == ["model", "owner"]
    assert values(enums.AssetKind) == ["image", "clip", "audio", "sprite"]
    assert values(enums.AssetOrigin) == ["generated", "uploaded", "library"]
    assert values(enums.RightsStatus) == ["cleared", "needs_review", "blocked"]
    assert values(enums.RenderKind) == ["preview", "draft", "final"]
    assert values(enums.ReviewVerdict) == ["finished", "adjust", "remake"]
    assert values(enums.AgentName) == ["critic", "producer"]
    assert values(enums.AgentRunStatus) == [
        "running",
        "finished",
        "limit_reached",
        "failed",
        "stopped_by_owner",
    ]
    assert values(enums.Provider) == [
        "demo",
        "claude_plan",
        "chatgpt_plan",
        "anthropic_api",
        "openai_api",
    ]
    assert values(enums.UsageKind) == ["text", "image"]
    assert values(enums.Billing) == ["demo", "plan", "api"]
    assert values(enums.ProviderState) == ["ok", "near_budget", "paused_by_budget", "limited"]
    assert values(enums.StatusSource) == ["tool", "app"]


def declared_default(table: str, column: str) -> object:
    default = Base.metadata.tables[table].c[column].default
    assert default is not None, f"{table}.{column} has no default"
    return getattr(default, "arg", None)


def test_new_rows_get_safe_defaults() -> None:
    assert declared_default("job", "status") == enums.JobStatus.QUEUED
    assert declared_default("job", "attempts") == 0
    assert declared_default("episode", "state") == enums.EpisodeState.IDEA
    assert declared_default("episode", "total_cost_usd") == Decimal("0")
    # Fail closed: a new asset blocks export until its rights are cleared (FR-08).
    assert declared_default("asset", "rights_status") == enums.RightsStatus.NEEDS_REVIEW
    assert models.Job(type="noop", tag=enums.JobTag.CPU).type == "noop"
