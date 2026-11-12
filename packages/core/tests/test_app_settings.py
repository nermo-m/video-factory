"""The "Use paid APIs" switch and the billing rules, on a real Postgres (section 3.4)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from packages.core import app_settings
from packages.core.db import models
from packages.core.enums import Billing, Provider, UsageKind

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


# --- the switch --------------------------------------------------------------------------


def test_fr28_paid_apis_are_off_until_the_owner_switches_them_on(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as session:
        assert app_settings.paid_apis_confirmed(session) is False


def test_the_switch_is_remembered_and_can_be_turned_off_again(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        app_settings.set_paid_apis_confirmed(session, True)
    with sessions() as session:
        assert app_settings.paid_apis_confirmed(session) is True

    with sessions.begin() as session:
        app_settings.set_paid_apis_confirmed(session, False)
    with sessions() as session:
        assert app_settings.paid_apis_confirmed(session) is False
        assert session.scalar(select(func.count()).select_from(models.Setting)) == 1


@pytest.mark.parametrize("stored", ["true", 1, "yes", None, {"on": True}])
def test_fr28_only_a_stored_true_counts_as_confirmation(
    sessions: sessionmaker[Session], stored: object
) -> None:
    # Whatever ends up in the table by another route, nothing but true switches paid APIs on.
    with sessions.begin() as session:
        app_settings.set_value(session, app_settings.USE_PAID_APIS, stored)

    with sessions() as session:
        assert app_settings.paid_apis_confirmed(session) is False


def test_other_settings_have_a_default_until_they_are_stored(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        assert app_settings.get_value(session, "budget", {"calls": 20}) == {"calls": 20}
        app_settings.set_value(session, "budget", {"calls": 5})

    with sessions() as session:
        assert app_settings.get_value(session, "budget", {"calls": 20}) == {"calls": 5}


# --- billing is kept honest by the database (FR-29) --------------------------------------


def model_call(provider: Provider, billing: Billing, cost: str = "0") -> models.ModelCall:
    return models.ModelCall(
        provider=provider, model="some-model", billing=billing, cost_usd=Decimal(cost)
    )


def usage(provider: Provider, billing: Billing, cost: str = "0") -> models.ProviderUsage:
    return models.ProviderUsage(
        provider=provider,
        model="some-model",
        kind=UsageKind.TEXT,
        billing=billing,
        cost_usd=Decimal(cost),
    )


@pytest.mark.parametrize("record", [model_call, usage])
@pytest.mark.parametrize(
    ("provider", "billing", "cost"),
    [
        (Provider.DEMO, Billing.DEMO, "0"),
        (Provider.CLAUDE_PLAN, Billing.PLAN, "0"),
        (Provider.CHATGPT_PLAN, Billing.PLAN, "0"),
        (Provider.ANTHROPIC_API, Billing.API, "0.0123"),
        (Provider.OPENAI_API, Billing.API, "0.04"),
    ],
)
def test_fr29_a_call_is_stored_with_the_billing_type_of_its_provider(
    sessions: sessionmaker[Session], record: object, provider: Provider, billing: Billing, cost: str
) -> None:
    with sessions.begin() as session:
        session.add(record(provider, billing, cost))  # type: ignore[operator]


@pytest.mark.parametrize("record", [model_call, usage])
@pytest.mark.parametrize(
    ("provider", "billing"),
    [
        (Provider.ANTHROPIC_API, Billing.PLAN),
        (Provider.OPENAI_API, Billing.DEMO),
        (Provider.CLAUDE_PLAN, Billing.API),
        (Provider.DEMO, Billing.PLAN),
    ],
)
def test_fr29_a_paid_call_cannot_be_stored_as_anything_else_or_the_other_way_round(
    sessions: sessionmaker[Session], record: object, provider: Provider, billing: Billing
) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(record(provider, billing))  # type: ignore[operator]


@pytest.mark.parametrize("record", [model_call, usage])
@pytest.mark.parametrize(
    ("provider", "billing"),
    [(Provider.CLAUDE_PLAN, Billing.PLAN), (Provider.DEMO, Billing.DEMO)],
)
def test_fr29_plan_and_demo_calls_never_carry_a_cost(
    sessions: sessionmaker[Session], record: object, provider: Provider, billing: Billing
) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(record(provider, billing, "0.01"))  # type: ignore[operator]
