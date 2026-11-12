"""The rules of the usage and limits tracker that need no database (section 3.5).

FR-31: usage is counted in windows of 5 hours and 7 days. FR-32: the owner's soft budgets
warn at 80 percent and pause at 100 percent, with an override for one episode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from packages.core.enums import Billing, Provider, ProviderState
from packages.core.limits import (
    Budget,
    BudgetError,
    Usage,
    Windows,
    budget_from_json,
    budget_state,
    default_budget,
    provider_for_job,
    share_used,
    why_not_now,
)

NOW = datetime(2026, 11, 12, 13, 0, tzinfo=UTC)


def windows(
    calls_5h: int = 0, calls_7d: int = 0, images_5h: int = 0, images_7d: int = 0
) -> Windows:
    return Windows(
        five_hours=Usage(calls=calls_5h, images=images_5h),
        seven_days=Usage(calls=calls_7d, images=images_7d),
    )


PLAN = Budget(calls_5h=10, calls_7d=100, images_5h=4, images_7d=20)


@pytest.mark.parametrize(
    ("used", "share"),
    [
        (windows(), 0.0),
        (windows(calls_5h=5, calls_7d=5), 0.5),
        (windows(calls_5h=2, calls_7d=90), 0.9),
        (windows(images_5h=4, images_7d=4), 1.0),
        (windows(calls_5h=1, calls_7d=1, images_5h=1, images_7d=19), 0.95),
        (windows(calls_5h=30, calls_7d=30), 3.0),
    ],
)
def test_fr32_the_fullest_window_decides_how_much_of_a_plan_budget_is_used(
    used: Windows, share: float
) -> None:
    assert share_used(used, PLAN, Billing.PLAN) == pytest.approx(share)


def test_fr32_a_paid_provider_is_measured_in_dollars() -> None:
    budget = Budget(usd_5h=Decimal("2"), usd_7d=Decimal("10"))
    used = Windows(
        five_hours=Usage(calls=500, cost_usd=Decimal("1")),
        seven_days=Usage(calls=900, cost_usd=Decimal("9")),
    )

    assert share_used(used, budget, Billing.API) == pytest.approx(0.9)


def test_demo_calls_use_no_budget() -> None:
    assert share_used(windows(calls_5h=999, calls_7d=999), PLAN, Billing.DEMO) == 0.0


def test_a_budget_of_zero_is_used_up_by_the_first_call_and_not_before() -> None:
    nothing = Budget(calls_5h=0, calls_7d=0, images_5h=0, images_7d=0)

    assert share_used(windows(), nothing, Billing.PLAN) == 0.0
    assert share_used(windows(calls_5h=1, calls_7d=1), nothing, Billing.PLAN) >= 1.0


@pytest.mark.parametrize(
    ("share", "state"),
    [
        (0.0, ProviderState.OK),
        (0.79, ProviderState.OK),
        (0.8, ProviderState.NEAR_BUDGET),
        (0.99, ProviderState.NEAR_BUDGET),
        (1.0, ProviderState.PAUSED_BY_BUDGET),
        (2.5, ProviderState.PAUSED_BY_BUDGET),
    ],
)
def test_fr32_a_budget_warns_at_80_percent_and_pauses_at_100(
    share: float, state: ProviderState
) -> None:
    assert budget_state(share) is state


def test_fr32_default_budgets_are_low_and_differ_by_how_a_provider_is_paid() -> None:
    plan, paid = default_budget(Provider.CLAUDE_PLAN), default_budget(Provider.ANTHROPIC_API)

    assert 0 < plan.calls_5h <= 30
    assert plan.calls_5h < plan.calls_7d
    assert 0 < plan.images_5h < plan.images_7d
    assert Decimal("0") < paid.usd_5h <= paid.usd_7d <= Decimal("10")


def test_a_budget_reads_back_what_it_writes() -> None:
    budget = Budget(
        calls_5h=3, calls_7d=9, images_5h=1, images_7d=2, usd_5h=Decimal("0.5"), usd_7d=Decimal("2")
    )

    assert budget_from_json(budget.to_json(), Provider.CLAUDE_PLAN) == budget


def test_a_budget_missing_some_numbers_keeps_the_defaults_for_them() -> None:
    budget = budget_from_json({"calls_5h": 7}, Provider.CLAUDE_PLAN)

    assert budget.calls_5h == 7
    assert budget.calls_7d == default_budget(Provider.CLAUDE_PLAN).calls_7d


@pytest.mark.parametrize(
    "written",
    [
        {"calls_5h": -1},
        {"calls_5h": 2.5},
        {"calls_5h": True},
        {"images_7d": "many"},
        {"usd_7d": "-3"},
        {"usd_5h": "a lot"},
        {"calls_5h": 10, "calls_7d": 5},
        {"usd_5h": "5", "usd_7d": "1"},
        {"surprise": 1},
        ["calls_5h"],
    ],
)
def test_a_budget_that_makes_no_sense_is_refused(written: object) -> None:
    with pytest.raises(BudgetError):
        budget_from_json(written, Provider.CLAUDE_PLAN)


@pytest.mark.parametrize(
    ("job_type", "mode", "provider"),
    [
        ("plan.brief", "subscription", Provider.CLAUDE_PLAN),
        ("plan.research", "api", Provider.ANTHROPIC_API),
        ("plan.package", "demo", Provider.DEMO),
        ("agent.critic", "subscription", Provider.CLAUDE_PLAN),
        ("gen.image", "subscription", Provider.CHATGPT_PLAN),
        ("gen.image", "api", Provider.OPENAI_API),
        ("render.scene", "subscription", None),
        ("qc.run", "api", None),
        ("noop", "demo", None),
    ],
)
def test_a_job_type_says_which_provider_the_job_needs(
    job_type: str, mode: str, provider: Provider | None
) -> None:
    assert provider_for_job(job_type, mode) is provider


def test_a_provider_that_is_ok_or_only_near_its_budget_may_work() -> None:
    for state in (ProviderState.OK, ProviderState.NEAR_BUDGET):
        assert why_not_now(Provider.CLAUDE_PLAN, state, None, now=NOW, overridden=False) is None


def test_fr32_a_paused_provider_says_so_and_an_override_lets_the_episode_through() -> None:
    state = ProviderState.PAUSED_BY_BUDGET

    reason = why_not_now(Provider.CLAUDE_PLAN, state, None, now=NOW, overridden=False)

    assert reason is not None
    assert "budget" in reason
    assert "Continue anyway" in reason
    assert why_not_now(Provider.CLAUDE_PLAN, state, None, now=NOW, overridden=True) is None


def test_fr31_a_limited_provider_waits_until_the_reset_time_whatever_the_override() -> None:
    until = NOW + timedelta(hours=2)

    for overridden in (False, True):
        reason = why_not_now(
            Provider.CHATGPT_PLAN, ProviderState.LIMITED, until, now=NOW, overridden=overridden
        )
        assert reason is not None
        assert "15:00" in reason
        assert "ChatGPT plan" in reason


def test_fr31_a_limit_without_a_reset_time_waits_for_the_next_check() -> None:
    reason = why_not_now(
        Provider.CLAUDE_PLAN, ProviderState.LIMITED, None, now=NOW, overridden=False
    )

    assert reason is not None
    assert "next check" in reason


def test_fr31_a_limit_whose_reset_time_has_passed_still_waits_for_the_probe() -> None:
    # Section 3.5: "A provider whose reset time has passed is probed once and set back to
    # ok if the probe succeeds." Until that probe, it stays limited.
    passed = NOW - timedelta(minutes=1)

    assert (
        why_not_now(Provider.CLAUDE_PLAN, ProviderState.LIMITED, passed, now=NOW, overridden=False)
        is not None
    )
