"""Provider modes and the paid API guard (design doc section 3.4, FR-28, FR-29). Pure rules."""

from __future__ import annotations

import pytest

from packages.core.enums import Billing, Provider
from packages.core.providers import (
    PaidApiRefusedError,
    billing_of,
    ensure_paid_apis_allowed,
    providers_for,
)
from packages.core.settings import PROVIDER_MODES


def test_every_mode_has_its_providers() -> None:
    assert set(PROVIDER_MODES) == {"demo", "subscription", "api"}

    demo, subscription, api = (providers_for(mode) for mode in ("demo", "subscription", "api"))

    assert (demo.text, demo.second_opinion, demo.image) == (Provider.DEMO,) * 3
    assert subscription.text is Provider.CLAUDE_PLAN
    assert subscription.second_opinion is Provider.CHATGPT_PLAN
    assert subscription.image is Provider.CHATGPT_PLAN
    assert api.text is Provider.ANTHROPIC_API
    assert api.image is Provider.OPENAI_API


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="paid"):
        providers_for("paid")


@pytest.mark.parametrize(
    ("provider", "billing"),
    [
        (Provider.DEMO, Billing.DEMO),
        (Provider.CLAUDE_PLAN, Billing.PLAN),
        (Provider.CHATGPT_PLAN, Billing.PLAN),
        (Provider.ANTHROPIC_API, Billing.API),
        (Provider.OPENAI_API, Billing.API),
    ],
)
def test_fr29_every_provider_has_one_billing_type(provider: Provider, billing: Billing) -> None:
    assert billing_of(provider) is billing


@pytest.mark.parametrize("mode", ["demo", "subscription"])
def test_fr28_only_api_mode_ever_names_a_paid_provider(mode: str) -> None:
    chosen = providers_for(mode)

    for provider in (chosen.text, chosen.second_opinion, chosen.image):
        assert billing_of(provider) is not Billing.API


def test_fr28_paid_apis_need_the_mode_and_the_switch_together() -> None:
    ensure_paid_apis_allowed("api", confirmed=True)


@pytest.mark.parametrize(
    ("mode", "confirmed", "says", "does_not_say"),
    [
        ("api", False, "'Use paid APIs' switch in Settings is off", "PROVIDER_MODE is"),
        ("subscription", True, "PROVIDER_MODE is 'subscription'", "switch in Settings is off"),
        ("demo", True, "PROVIDER_MODE is 'demo'", "switch in Settings is off"),
    ],
)
def test_fr28_a_refusal_says_which_condition_is_missing(
    mode: str, confirmed: bool, says: str, does_not_say: str
) -> None:
    with pytest.raises(PaidApiRefusedError) as refused:
        ensure_paid_apis_allowed(mode, confirmed=confirmed)

    assert says in str(refused.value)
    assert does_not_say not in str(refused.value)


def test_fr28_with_both_missing_the_refusal_names_both() -> None:
    with pytest.raises(PaidApiRefusedError) as refused:
        ensure_paid_apis_allowed("subscription", confirmed=False)

    assert "PROVIDER_MODE is 'subscription'" in str(refused.value)
    assert "switch in Settings is off" in str(refused.value)
    assert "never switches to a paid API by itself" in str(refused.value)
