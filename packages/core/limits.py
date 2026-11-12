"""Usage and limits tracker (design doc section 3.5, FR-31, FR-32, FR-34).

The owner's plans are shared with his own work, so this app counts what it uses and stops
before it uses too much. Three things are known, in order of trust:

1. Limit events: a tool said its limit was reached. Exact. Stored with source `tool`.
2. What the tools report about remaining quota. Neither installed tool reports it in a
   form a program can read (question Q-044), so nothing of this kind is stored.
3. This app's own count of calls, tokens and images in the last 5 hours and 7 days.
   Stored with source `app`, and never to be shown as the plan's real remaining quota.

The first half of this module is rules without a database. The second half applies them
to the tables `provider_usage` and `provider_status`. Its functions take a Session and
never commit.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from packages.core import app_settings
from packages.core.db.models import Job, ProviderStatus, ProviderUsage
from packages.core.enums import (
    Billing,
    ErrorClass,
    JobStatus,
    Provider,
    ProviderState,
    StatusSource,
    UsageKind,
)
from packages.core.providers import billing_of, providers_for
from packages.core.queue import JobError, PlanLimitError

ZERO = Decimal("0")
FIVE_HOURS = timedelta(hours=5)
SEVEN_DAYS = timedelta(days=7)
WARN_AT = 0.8
PAUSE_AT = 1.0
# "Check limits now" may run this often (section 3.5).
MANUAL_CHECK_EVERY_S = 30
TITLES = {
    Provider.DEMO: "Demo recordings",
    Provider.CLAUDE_PLAN: "Claude plan",
    Provider.CHATGPT_PLAN: "ChatGPT plan",
    Provider.ANTHROPIC_API: "Anthropic API",
    Provider.OPENAI_API: "OpenAI API",
}


# --- Rules -----------------------------------------------------------------------------


class BudgetError(ValueError):
    """A budget the owner entered cannot be used. The message says which number and why."""


@dataclass(frozen=True)
class Budget:
    """The share of each window this app may use (section 3.5, "Owner budgets").

    Plans are budgeted in calls and images. Paid providers are budgeted in dollars.
    """

    calls_5h: int = 0
    calls_7d: int = 0
    images_5h: int = 0
    images_7d: int = 0
    usd_5h: Decimal = ZERO
    usd_7d: Decimal = ZERO

    def to_json(self) -> dict[str, Any]:
        return {name: str(v) if isinstance(v, Decimal) else v for name, v in asdict(self).items()}


# "Defaults are deliberately low": the owner raises them once he sees his own usage.
_PLAN_DEFAULT = Budget(calls_5h=20, calls_7d=150, images_5h=5, images_7d=30)
_API_DEFAULT = Budget(usd_5h=Decimal("1"), usd_7d=Decimal("5"))


def default_budget(provider: Provider) -> Budget:
    billing = billing_of(provider)
    if billing is Billing.PLAN:
        return _PLAN_DEFAULT
    return _API_DEFAULT if billing is Billing.API else Budget()


def budget_from_json(written: object, provider: Provider) -> Budget:
    """A budget from stored or entered numbers. Missing numbers keep their defaults."""
    if not isinstance(written, Mapping):
        raise BudgetError("A budget is a set of named numbers.")
    budget = default_budget(provider)
    known = asdict(budget)
    unknown = sorted(str(name) for name in written if name not in known)
    if unknown:
        raise BudgetError(f"Unknown budget number: {', '.join(unknown)}.")
    values: dict[str, Any] = {}
    for name, value in written.items():
        if name.startswith("usd_"):
            try:
                amount = Decimal(str(value))
            except InvalidOperation:
                amount = Decimal("NaN")
            if isinstance(value, bool) or not amount.is_finite() or amount < 0:
                raise BudgetError(f"`{name}` must be an amount of 0 or more.")
            values[name] = amount
        else:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BudgetError(f"`{name}` must be a whole number of 0 or more.")
            values[name] = value
    budget = replace(budget, **values)
    for kind in ("calls", "images", "usd"):
        if getattr(budget, f"{kind}_5h") > getattr(budget, f"{kind}_7d"):
            raise BudgetError(
                f"`{kind}_5h` cannot be larger than `{kind}_7d`: the 5 hours lie inside the 7 days."
            )
    return budget


@dataclass(frozen=True)
class Usage:
    """What this app used of one provider in one window. Counted by this app."""

    calls: int = 0
    images: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = ZERO


@dataclass(frozen=True)
class Windows:
    five_hours: Usage = field(default_factory=Usage)
    seven_days: Usage = field(default_factory=Usage)


def _ratio(used: float, allowed: float) -> float:
    if allowed > 0:
        return used / allowed
    # A budget of zero allows nothing: the first use is already over it.
    return PAUSE_AT if used > 0 else 0.0


def share_used(used: Windows, budget: Budget, billing: Billing) -> float:
    """How full the fullest window is, where 1.0 means the budget is used up."""
    if billing is Billing.DEMO:
        return 0.0
    five, seven = used.five_hours, used.seven_days
    if billing is Billing.API:
        return max(
            _ratio(float(five.cost_usd), float(budget.usd_5h)),
            _ratio(float(seven.cost_usd), float(budget.usd_7d)),
        )
    return max(
        _ratio(five.calls, budget.calls_5h),
        _ratio(seven.calls, budget.calls_7d),
        _ratio(five.images, budget.images_5h),
        _ratio(seven.images, budget.images_7d),
    )


def budget_state(share: float) -> ProviderState:
    """FR-32: warn at 80 percent of a budget, pause at 100 percent."""
    if share >= PAUSE_AT:
        return ProviderState.PAUSED_BY_BUDGET
    return ProviderState.NEAR_BUDGET if share >= WARN_AT else ProviderState.OK


def provider_for_job(job_type: str, mode: str) -> Provider | None:
    """The provider a job of this type calls in this mode, or None when it calls none."""
    providers = providers_for(mode)
    if job_type.startswith(("plan.", "agent.")):
        return providers.text
    if job_type == "gen.image":
        return providers.image
    return None


def why_not_now(
    provider: Provider,
    state: ProviderState,
    limited_until: datetime | None,
    *,
    now: datetime,
    overridden: bool,
) -> str | None:
    """The reason a job of this provider has to wait, or None when it may start.

    The override is the owner's "Continue anyway" for one episode. It lifts a budget pause,
    which is this app's own caution. It cannot lift a limit, which is the plan's.
    """
    title = TITLES[provider]
    if state is ProviderState.LIMITED:
        if limited_until is None:
            return (
                f"The {title} has reached its usage limit and gave no reset time. "
                "The job waits for the next check."
            )
        if limited_until <= now:
            return (
                f"The {title} was limited. The job waits for the next check to confirm it is back."
            )
        local = limited_until.astimezone(now.tzinfo)
        return (
            f"The {title} has reached its usage limit. The job waits until {local:%H:%M on %d %b}."
        )
    if state is ProviderState.PAUSED_BY_BUDGET and not overridden:
        return (
            f"This app has used its budget for the {title}. The job waits until the window "
            'moves on, or until you press "Continue anyway" for this episode.'
        )
    return None


# --- Tables ----------------------------------------------------------------------------

_BUDGET_KEY = "budget.{provider}"
_OVERRIDE_KEY = "budget_override.{provider}"
_LAST_MANUAL_CHECK_KEY = "limits.last_manual_check"


def record_usage(
    session: Session,
    *,
    provider: Provider,
    model: str,
    kind: UsageKind = UsageKind.TEXT,
    input_tokens: int = 0,
    output_tokens: int = 0,
    images: int = 0,
    cost_usd: Decimal = ZERO,
    job_id: uuid.UUID | None = None,
) -> ProviderUsage:
    """Count one use of a provider. Plan and demo uses store cost 0."""
    billing = billing_of(provider)
    row = ProviderUsage(
        provider=provider,
        model=model,
        kind=kind,
        job_id=job_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        images=images,
        billing=billing,
        cost_usd=cost_usd if billing is Billing.API else ZERO,
    )
    session.add(row)
    session.flush()
    return row


def _usage_since(session: Session, provider: Provider, since: datetime, until: datetime) -> Usage:
    calls, images, tokens_in, tokens_out, cost = session.execute(
        select(
            func.count().filter(ProviderUsage.kind == UsageKind.TEXT),
            func.coalesce(func.sum(ProviderUsage.images), 0),
            func.coalesce(func.sum(ProviderUsage.input_tokens), 0),
            func.coalesce(func.sum(ProviderUsage.output_tokens), 0),
            func.coalesce(func.sum(ProviderUsage.cost_usd), 0),
        ).where(
            ProviderUsage.provider == provider,
            ProviderUsage.created_at > since,
            ProviderUsage.created_at <= until,
        )
    ).one()
    return Usage(int(calls), int(images), int(tokens_in), int(tokens_out), Decimal(cost))


def window_usage(session: Session, provider: Provider, *, now: datetime) -> Windows:
    """FR-31: this app's use of a provider in the last 5 hours and the last 7 days."""
    return Windows(
        five_hours=_usage_since(session, provider, now - FIVE_HOURS, now),
        seven_days=_usage_since(session, provider, now - SEVEN_DAYS, now),
    )


def get_budget(session: Session, provider: Provider) -> Budget:
    stored = app_settings.get_value(session, _BUDGET_KEY.format(provider=provider.value))
    return default_budget(provider) if stored is None else budget_from_json(stored, provider)


def set_budget(session: Session, provider: Provider, written: object) -> Budget:
    """Store the owner's budget. Raises BudgetError when it makes no sense."""
    budget = budget_from_json(written, provider)
    app_settings.set_value(session, _BUDGET_KEY.format(provider=provider.value), budget.to_json())
    return budget


def allow_episode(session: Session, provider: Provider, episode_id: uuid.UUID) -> None:
    """The owner's "Continue anyway": this episode may pass a budget pause of this provider."""
    key = _OVERRIDE_KEY.format(provider=provider.value)
    allowed = set(app_settings.get_value(session, key, []))
    allowed.add(str(episode_id))
    app_settings.set_value(session, key, sorted(allowed))
    _resume_jobs(session, provider, episode_id=episode_id)


def is_allowed(session: Session, provider: Provider, episode_id: uuid.UUID | None) -> bool:
    if episode_id is None:
        return False
    key = _OVERRIDE_KEY.format(provider=provider.value)
    return str(episode_id) in app_settings.get_value(session, key, [])


def _status(session: Session, provider: Provider) -> ProviderStatus:
    """The provider's status row, locked, created when it does not exist yet."""
    row = session.scalar(
        select(ProviderStatus).where(ProviderStatus.provider == provider).with_for_update()
    )
    if row is None:
        row = ProviderStatus(provider=provider, state=ProviderState.OK, source=StatusSource.APP)
        session.add(row)
        session.flush()
    return row


def refresh(session: Session, provider: Provider, *, now: datetime) -> ProviderStatus:
    """Bring the state in line with the budget. A limit stays until a check lifts it."""
    row = _status(session, provider)
    if row.state is not ProviderState.LIMITED:
        used = window_usage(session, provider, now=now)
        share = share_used(used, get_budget(session, provider), billing_of(provider))
        row.state = budget_state(share)
        row.source = StatusSource.APP
        row.limited_until = None
    return row


def limit_reached(
    session: Session,
    provider: Provider,
    *,
    message: str,
    retry_at: datetime | None,
    now: datetime,
) -> ProviderStatus:
    """FR-31: a tool reported its limit. The provider is limited until the reset time."""
    row = _status(session, provider)
    row.state = ProviderState.LIMITED
    row.source = StatusSource.TOOL
    row.limited_until = retry_at
    row.last_checked_at = now
    row.last_error = message
    return row


def gate(
    session: Session, provider: Provider, *, episode_id: uuid.UUID | None, now: datetime
) -> tuple[str, datetime | None] | None:
    """Asked before a job starts. None lets it start. Otherwise the reason it waits, and
    the time it can try again when that is known."""
    row = refresh(session, provider, now=now)
    reason = why_not_now(
        provider,
        row.state,
        row.limited_until,
        now=now,
        overridden=is_allowed(session, provider, episode_id),
    )
    if reason is None:
        return None
    waits_until = row.limited_until if row.limited_until and row.limited_until > now else None
    return reason, waits_until


@dataclass(frozen=True)
class ProviderView:
    """Everything the interface shows about one provider (section 10, `GET /providers`)."""

    provider: Provider
    title: str
    billing: Billing
    state: ProviderState
    # Who said so: `tool` for a limit a tool reported, `app` for this app's own count.
    state_source: StatusSource
    limited_until: datetime | None
    last_checked_at: datetime | None
    last_error: str | None
    usage: Windows
    budget: Budget
    share: float


def view(session: Session, provider: Provider, *, now: datetime) -> ProviderView:
    row = refresh(session, provider, now=now)
    used = window_usage(session, provider, now=now)
    budget = get_budget(session, provider)
    return ProviderView(
        provider=provider,
        title=TITLES[provider],
        billing=billing_of(provider),
        state=row.state,
        state_source=row.source,
        limited_until=row.limited_until,
        last_checked_at=row.last_checked_at,
        last_error=row.last_error,
        usage=used,
        budget=budget,
        share=share_used(used, budget, billing_of(provider)),
    )


def providers_of(mode: str) -> list[Provider]:
    """The providers of a mode, each once, in the order text, second opinion, image."""
    chosen = providers_for(mode)
    return list(dict.fromkeys([chosen.text, chosen.second_opinion, chosen.image]))


def snapshot(session: Session, mode: str, *, now: datetime) -> list[ProviderView]:
    return [view(session, provider, now=now) for provider in providers_of(mode)]


# --- The check (FR-34) -------------------------------------------------------------------


class Probe(Protocol):
    """How the check looks at a provider. Implemented next to the adapters."""

    def free_check(self, provider: Provider) -> str | None:
        """Costs nothing: is the tool installed and signed in. Returns what is wrong, or None."""

    def tiny_call(self, provider: Provider) -> None:
        """One tiny model call. Raises PlanLimitError while the limit holds, another
        JobError when the call could not be made."""


class CheckTooSoonError(Exception):
    """ "Check limits now" was pressed again within 30 seconds."""

    def __init__(self, wait_s: int) -> None:
        super().__init__(f"The limits were checked a moment ago. Try again in {wait_s} seconds.")
        self.wait_s = wait_s


def check(
    session: Session, mode: str, probe: Probe, *, now: datetime, on_demand: bool = False
) -> list[ProviderView]:
    """Look at every provider of the mode and return where each one stands.

    The free check runs for every provider. The tiny call, which spends plan usage, runs
    only for a provider that is limited: routinely once its reset time has passed or when
    it gave none, and on demand always. A successful call lifts the limit and lets the
    waiting jobs run. Budget counts are never reset: they follow the windows.
    """
    if on_demand:
        last = app_settings.get_value(session, _LAST_MANUAL_CHECK_KEY)
        if isinstance(last, str):
            waited = (now - datetime.fromisoformat(last)).total_seconds()
            if 0 <= waited < MANUAL_CHECK_EVERY_S:
                raise CheckTooSoonError(max(1, round(MANUAL_CHECK_EVERY_S - waited)))
        app_settings.set_value(session, _LAST_MANUAL_CHECK_KEY, now.isoformat())

    for provider in providers_of(mode):
        if billing_of(provider) is Billing.DEMO:
            continue
        row = _status(session, provider)
        problem = probe.free_check(provider)
        row.last_checked_at = now
        limited = row.state is ProviderState.LIMITED
        due = on_demand or row.limited_until is None or row.limited_until <= now
        if limited and due and problem is None:
            try:
                probe.tiny_call(provider)
            except PlanLimitError as still:
                row.limited_until = still.retry_at
                row.last_error = str(still)
            except JobError as failed:
                row.last_error = str(failed)
            else:
                row.state = ProviderState.OK
                row.limited_until = None
                row.last_error = None
                _resume_jobs(session, provider, mode=mode)
        elif not limited or problem is not None:
            row.last_error = problem
        refresh(session, provider, now=now)
    return snapshot(session, mode, now=now)


def _resume_jobs(
    session: Session,
    provider: Provider,
    *,
    mode: str | None = None,
    episode_id: uuid.UUID | None = None,
) -> None:
    """Let queued jobs that were waiting for this provider be claimed again now."""
    waiting = update(Job).where(
        Job.status == JobStatus.QUEUED, Job.error_class == ErrorClass.PLAN_LIMIT
    )
    if episode_id is not None:
        waiting = waiting.where(Job.episode_id == episode_id)
    elif mode is not None:
        kinds = [
            prefix
            for prefix, example in (
                ("plan.", "plan.brief"),
                ("agent.", "agent.critic"),
                ("gen.image", "gen.image"),
            )
            if provider_for_job(example, mode) is provider
        ]
        if not kinds:
            return
        waiting = waiting.where(or_(*[Job.type.startswith(kind) for kind in kinds]))
    session.execute(waiting.values(run_after=func.now()))
