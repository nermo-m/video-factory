"""Providers, their limits and the owner's budgets (design doc sections 3.5 and 10).

    GET  /providers                  where each provider of the current mode stands
    PUT  /providers/{id}/budget      set the owner's soft budget
    POST /providers/{id}/continue    let one episode pass a budget pause
    POST /providers/check            check the limits now, at most once in 30 seconds

Every usage number here is counted by this app. It is never the plan's real remaining
quota, which neither plan reports, and the response says so in `usage_source`. A state
says who it comes from in `state_source`: `tool` when a tool reported a limit, `app` when
it follows from this app's own count against the budget.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Request
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from apps.api.errors import BAD_BODY_RESPONSE, ApiError, ErrorResponse
from packages.core import limits
from packages.core.db.models import Episode
from packages.core.enums import Billing, Provider, ProviderState, StatusSource

router = APIRouter(tags=["providers"])
# Dollars with up to four decimals, below one million.
AMOUNT = r"^[0-9]{1,6}(\.[0-9]{1,4})?$"


class UnknownEpisodeError(LookupError):
    """The episode a "Continue anyway" names does not exist."""


class ProviderService(Protocol):
    """What the routes need. The real one works on the database, tests bring their own."""

    def overview(self) -> list[limits.ProviderView]: ...

    def set_budget(self, provider: Provider, numbers: dict[str, Any]) -> None: ...

    def continue_anyway(self, provider: Provider, episode_id: uuid.UUID) -> None: ...

    def check_now(self) -> list[limits.ProviderView]: ...


class DatabaseProviderService:
    def __init__(self, sessions: sessionmaker[Session], mode: str, probe: limits.Probe) -> None:
        self._sessions = sessions
        self._mode = mode
        self._probe = probe

    def overview(self) -> list[limits.ProviderView]:
        with self._sessions.begin() as session:
            return limits.snapshot(session, self._mode, now=datetime.now(UTC))

    def set_budget(self, provider: Provider, numbers: dict[str, Any]) -> None:
        with self._sessions.begin() as session:
            current = limits.get_budget(session, provider).to_json()
            limits.set_budget(session, provider, {**current, **numbers})

    def continue_anyway(self, provider: Provider, episode_id: uuid.UUID) -> None:
        with self._sessions.begin() as session:
            if session.get(Episode, episode_id) is None:
                raise UnknownEpisodeError(str(episode_id))
            limits.allow_episode(session, provider, episode_id)

    def check_now(self) -> list[limits.ProviderView]:
        with self._sessions.begin() as session:
            return limits.check(
                session, self._mode, self._probe, now=datetime.now(UTC), on_demand=True
            )


class MemoryProviderService:
    """Keeps nothing but the demo provider. For tests and for exporting the OpenAPI file."""

    def __init__(self, views: list[limits.ProviderView] | None = None) -> None:
        self.views = views if views is not None else [demo_view()]

    def overview(self) -> list[limits.ProviderView]:
        return self.views

    def set_budget(self, provider: Provider, numbers: dict[str, Any]) -> None:
        limits.budget_from_json(numbers, provider)

    def continue_anyway(self, provider: Provider, episode_id: uuid.UUID) -> None:
        return None

    def check_now(self) -> list[limits.ProviderView]:
        return self.views


def demo_view() -> limits.ProviderView:
    return limits.ProviderView(
        provider=Provider.DEMO,
        title=limits.TITLES[Provider.DEMO],
        billing=Billing.DEMO,
        state=ProviderState.OK,
        state_source=StatusSource.APP,
        limited_until=None,
        last_checked_at=None,
        last_error=None,
        usage=limits.Windows(),
        budget=limits.Budget(),
        share=0.0,
    )


# --- What travels ------------------------------------------------------------------------


class UsageOut(BaseModel):
    calls: int = Field(description="Text calls in the window.")
    images: int
    input_tokens: int
    output_tokens: int
    cost_usd: str = Field(description="Real cost for a paid provider, 0 for a plan.")


class WindowsOut(BaseModel):
    five_hours: UsageOut
    seven_days: UsageOut


class BudgetOut(BaseModel):
    calls_5h: int
    calls_7d: int
    images_5h: int
    images_7d: int
    usd_5h: str
    usd_7d: str


class ProviderOut(BaseModel):
    id: Provider
    title: str
    billing: Billing = Field(description="demo, plan or api.")
    state: ProviderState = Field(description="ok, near_budget, paused_by_budget or limited.")
    state_source: StatusSource = Field(
        description="tool: a tool reported the limit. app: follows from this app's own count."
    )
    limited_until: datetime | None = Field(description="When a limit resets, if the tool said so.")
    last_checked_at: datetime | None
    last_error: str | None = Field(description="What the last check or limit event said.")
    usage: WindowsOut
    usage_source: Literal["app"] = Field(
        description="Usage is counted by this app. It is not the plan's remaining quota."
    )
    budget: BudgetOut
    budget_used: float = Field(description="Share of the budget used, 1.0 is all of it.")


class ProvidersResponse(BaseModel):
    providers: list[ProviderOut]


def _whole_number(value: object) -> object:
    """JSON has one kind of number, so 150.0 is the whole number 150. Text and true or
    false are not numbers at all."""
    if isinstance(value, bool | str):
        raise ValueError("must be a whole number")
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


Count = Annotated[int, Field(ge=0, le=100_000), BeforeValidator(_whole_number)]


class BudgetUpdate(BaseModel):
    """Numbers that are left out keep their value."""

    model_config = ConfigDict(extra="forbid")

    calls_5h: Count | None = None
    calls_7d: Count | None = None
    images_5h: Count | None = None
    images_7d: Count | None = None
    # Money travels as text, so an amount arrives exactly as it was typed.
    usd_5h: Annotated[str, Field(pattern=AMOUNT)] | None = None
    usd_7d: Annotated[str, Field(pattern=AMOUNT)] | None = None


class ContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_id: uuid.UUID


def _usage(used: limits.Usage) -> UsageOut:
    return UsageOut(
        calls=used.calls,
        images=used.images,
        input_tokens=used.input_tokens,
        output_tokens=used.output_tokens,
        cost_usd=str(used.cost_usd),
    )


def _answer(views: list[limits.ProviderView]) -> ProvidersResponse:
    return ProvidersResponse(
        providers=[
            ProviderOut(
                id=view.provider,
                title=view.title,
                billing=view.billing,
                state=view.state,
                state_source=view.state_source,
                limited_until=view.limited_until,
                last_checked_at=view.last_checked_at,
                last_error=view.last_error,
                usage=WindowsOut(
                    five_hours=_usage(view.usage.five_hours),
                    seven_days=_usage(view.usage.seven_days),
                ),
                usage_source="app",
                budget=BudgetOut(**view.budget.to_json()),
                budget_used=round(view.share, 4),
            )
            for view in views
        ]
    )


def _service(request: Request) -> ProviderService:
    service: ProviderService = request.app.state.provider_service
    return service


def _in_this_mode(service: ProviderService, provider: Provider) -> None:
    if provider not in {view.provider for view in service.overview()}:
        raise ApiError(
            404,
            "provider_not_in_use",
            f"The provider '{provider.value}' is not used in the current provider mode.",
        )


NOT_IN_USE: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "The provider is not used in this mode."},
}


@router.get("/providers", summary="Each provider with its state, usage and budget")
def get_providers(request: Request) -> ProvidersResponse:
    return _answer(_service(request).overview())


@router.put(
    "/providers/{provider}/budget",
    summary="Set the owner's soft budget for a provider",
    responses={
        **BAD_BODY_RESPONSE,
        **NOT_IN_USE,
        409: {"model": ErrorResponse, "description": "The numbers contradict each other."},
    },
)
def put_provider_budget(
    provider: Provider, update: BudgetUpdate, request: Request
) -> ProvidersResponse:
    service = _service(request)
    _in_this_mode(service, provider)
    numbers = update.model_dump(exclude_none=True)
    try:
        service.set_budget(provider, numbers)
    except limits.BudgetError as error:
        # The numbers are each valid and conflict with one another.
        raise ApiError(409, "invalid_budget", str(error)) from error
    return _answer(service.overview())


@router.post(
    "/providers/{provider}/continue",
    summary='"Continue anyway": let one episode pass a budget pause of this provider',
    responses={
        **BAD_BODY_RESPONSE,
        404: {
            "model": ErrorResponse,
            "description": "The provider is not used in this mode, or the episode does not exist.",
        },
    },
)
def post_provider_continue(
    provider: Provider, body: ContinueRequest, request: Request
) -> ProvidersResponse:
    service = _service(request)
    _in_this_mode(service, provider)
    try:
        service.continue_anyway(provider, body.episode_id)
    except UnknownEpisodeError as error:
        raise ApiError(404, "episode_not_found", "This episode does not exist.") from error
    return _answer(service.overview())


@router.post(
    "/providers/check",
    summary="Check the limits of every provider now",
    responses={
        429: {
            "model": ErrorResponse,
            "description": "The limits were checked less than 30 seconds ago.",
        },
    },
)
def post_providers_check(request: Request) -> ProvidersResponse:
    try:
        return _answer(_service(request).check_now())
    except limits.CheckTooSoonError as error:
        raise ApiError(
            429, "checked_too_recently", str(error), details={"retry_after_s": error.wait_s}
        ) from error
