"""Provider modes and the paid API guard (design doc section 3.4, FR-28, FR-29).

One setting, PROVIDER_MODE, decides how models are reached. It is read once at start-up
and never changes by itself: not on errors, not on usage limits, not when keys happen to be
present. Paid APIs need two things together, the mode `api` and the "Use paid APIs" switch
in Settings, which the owner turns on by hand.

This module is pure: it holds the tables and the guard.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.core.enums import Billing, Provider


@dataclass(frozen=True)
class ModeProviders:
    """Who answers in one provider mode."""

    text: Provider  # planning skills, critic scoring, producer decisions
    second_opinion: Provider  # the independent second review inside the critic
    image: Provider


_BY_MODE: dict[str, ModeProviders] = {
    "demo": ModeProviders(Provider.DEMO, Provider.DEMO, Provider.DEMO),
    "subscription": ModeProviders(
        Provider.CLAUDE_PLAN, Provider.CHATGPT_PLAN, Provider.CHATGPT_PLAN
    ),
    "api": ModeProviders(Provider.ANTHROPIC_API, Provider.OPENAI_API, Provider.OPENAI_API),
}
_BILLING: dict[Provider, Billing] = {
    Provider.DEMO: Billing.DEMO,
    Provider.CLAUDE_PLAN: Billing.PLAN,
    Provider.CHATGPT_PLAN: Billing.PLAN,
    Provider.ANTHROPIC_API: Billing.API,
    Provider.OPENAI_API: Billing.API,
}


class PaidApiRefusedError(Exception):
    """A paid API was asked for without the owner having switched it on.

    The message says which of the two conditions is missing.
    """


def providers_for(mode: str) -> ModeProviders:
    """The providers of a mode. There is no fallback from one mode to another."""
    try:
        return _BY_MODE[mode]
    except KeyError:
        raise ValueError(
            f"'{mode}' is not a provider mode. The modes are: {', '.join(_BY_MODE)}."
        ) from None


def billing_of(provider: Provider) -> Billing:
    """How calls to a provider are paid for: demo, plan or api (FR-29)."""
    return _BILLING[provider]


def ensure_paid_apis_allowed(mode: str, *, confirmed: bool) -> None:
    """Raise PaidApiRefusedError unless the mode is `api` and the Settings switch is on."""
    missing = []
    if mode != "api":
        missing.append(f"PROVIDER_MODE is '{mode}', not 'api'")
    if not confirmed:
        missing.append("the 'Use paid APIs' switch in Settings is off")
    if missing:
        raise PaidApiRefusedError(
            f"Paid APIs are off: {' and '.join(missing)}. Both are needed, and the app "
            "never switches to a paid API by itself."
        )
