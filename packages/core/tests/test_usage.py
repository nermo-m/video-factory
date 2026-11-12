"""Model call logging on a real Postgres (FR-17, FR-29)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from packages.core import queue, usage
from packages.core.db import models
from packages.core.enums import Billing, JobTag, Provider

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


def stored(sessions: sessionmaker[Session]) -> models.ModelCall:
    with sessions() as session:
        return session.scalars(select(models.ModelCall)).one()


def test_fr17_a_paid_call_is_stored_with_its_tokens_cost_and_job(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        job = queue.enqueue(session, job_type="plan.brief", tag=JobTag.CPU)
        usage.record_model_call(
            session,
            provider=Provider.ANTHROPIC_API,
            model="claude-opus-5-5",
            skill="brief",
            skill_version="1.0",
            input_hash="a" * 64,
            input_tokens=1200,
            output_tokens=340,
            cost_usd=Decimal("0.0116"),
            latency_ms=2150,
            job_id=job.id,
        )

    call = stored(sessions)
    assert call.job_id == job.id
    assert (call.provider, call.billing) == (Provider.ANTHROPIC_API, Billing.API)
    assert (call.model, call.skill, call.skill_version) == ("claude-opus-5-5", "brief", "1.0")
    assert (call.input_tokens, call.output_tokens, call.latency_ms) == (1200, 340, 2150)
    assert call.cost_usd == Decimal("0.0116")
    assert call.input_hash == "a" * 64


@pytest.mark.parametrize(
    ("provider", "billing"),
    [
        (Provider.DEMO, Billing.DEMO),
        (Provider.CLAUDE_PLAN, Billing.PLAN),
        (Provider.CHATGPT_PLAN, Billing.PLAN),
        (Provider.OPENAI_API, Billing.API),
    ],
)
def test_fr29_the_billing_type_follows_from_the_provider(
    sessions: sessionmaker[Session], provider: Provider, billing: Billing
) -> None:
    with sessions.begin() as session:
        usage.record_model_call(
            session,
            provider=provider,
            model="some-model",
            input_tokens=10,
            output_tokens=5,
            cost_usd=Decimal("0"),
            latency_ms=1,
        )

    assert stored(sessions).billing is billing


@pytest.mark.parametrize("provider", [Provider.CLAUDE_PLAN, Provider.DEMO])
def test_fr29_plan_and_demo_calls_record_cost_zero_whatever_is_passed_in(
    sessions: sessionmaker[Session], provider: Provider
) -> None:
    with sessions.begin() as session:
        usage.record_model_call(
            session,
            provider=provider,
            model="some-model",
            input_tokens=10,
            output_tokens=5,
            cost_usd=Decimal("0.25"),
            latency_ms=1,
        )

    assert stored(sessions).cost_usd == Decimal("0")


def test_a_call_made_outside_a_job_is_stored_without_one(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        usage.record_model_call(
            session,
            provider=Provider.DEMO,
            model="recorded",
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
            latency_ms=0,
        )

    call = stored(sessions)
    assert call.job_id is None
    assert call.skill is None
