"""The usage and limits tracker on a real Postgres (section 3.5, FR-31, FR-32, FR-34)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from packages.core import limits, queue, usage
from packages.core.db import models
from packages.core.enums import (
    ErrorClass,
    JobStatus,
    JobTag,
    Provider,
    ProviderState,
    StatusSource,
    UsageKind,
)
from packages.core.queue import PlanLimitError, RetryableError

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 12, 13, 0, tzinfo=UTC)
CLAUDE, CHATGPT = Provider.CLAUDE_PLAN, Provider.CHATGPT_PLAN


@pytest.fixture
def sessions(migrated: Engine) -> sessionmaker[Session]:
    return sessionmaker(migrated, expire_on_commit=False)


def used(session: Session, provider: Provider, *, ago: timedelta, **fields: object) -> None:
    """One use of a provider, some time before NOW."""
    row = limits.record_usage(session, provider=provider, model="m", **fields)  # type: ignore[arg-type]
    row.created_at = NOW - ago
    session.flush()


class FakeProbe:
    """Stands in for the tools: says what is wrong, and answers or refuses the tiny call."""

    def __init__(self, *, problem: str | None = None, call: Exception | None = None) -> None:
        self.problem, self.call = problem, call
        self.free: list[Provider] = []
        self.called: list[Provider] = []

    def free_check(self, provider: Provider) -> str | None:
        self.free.append(provider)
        return self.problem

    def tiny_call(self, provider: Provider) -> None:
        self.called.append(provider)
        if self.call is not None:
            raise self.call


def test_fr31_usage_is_counted_in_a_5_hour_and_a_7_day_window(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        used(session, CLAUDE, ago=timedelta(minutes=1), input_tokens=100, output_tokens=10)
        used(session, CLAUDE, ago=timedelta(hours=4, minutes=59), input_tokens=50)
        used(session, CLAUDE, ago=timedelta(hours=5, minutes=1))
        used(session, CLAUDE, ago=timedelta(days=6, hours=23))
        used(session, CLAUDE, ago=timedelta(days=7, minutes=1))
        used(session, CHATGPT, ago=timedelta(minutes=5), kind=UsageKind.IMAGE, images=1)

        claude = limits.window_usage(session, CLAUDE, now=NOW)
        chatgpt = limits.window_usage(session, CHATGPT, now=NOW)

    assert (claude.five_hours.calls, claude.seven_days.calls) == (2, 4)
    assert (claude.five_hours.input_tokens, claude.five_hours.output_tokens) == (150, 10)
    # An image is counted as an image, not as a call.
    assert (chatgpt.five_hours.calls, chatgpt.five_hours.images) == (0, 1)


def test_fr31_the_window_moves_on_with_the_clock(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        used(session, CLAUDE, ago=timedelta(hours=4))

        later = limits.window_usage(session, CLAUDE, now=NOW + timedelta(hours=2))

    assert (later.five_hours.calls, later.seven_days.calls) == (0, 1)


def test_fr29_a_recorded_model_call_is_also_counted_as_usage(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        job = queue.enqueue(session, job_type="plan.brief", tag=JobTag.CPU)
        usage.record_model_call(
            session,
            provider=CLAUDE,
            model="claude-opus-5-5",
            input_tokens=412,
            output_tokens=18,
            cost_usd=Decimal("0.5"),
            latency_ms=900,
            job_id=job.id,
        )

    with sessions() as session:
        row = session.scalars(select(models.ProviderUsage)).one()
    assert (row.provider, row.model, row.kind) == (CLAUDE, "claude-opus-5-5", UsageKind.TEXT)
    assert (row.input_tokens, row.output_tokens, row.job_id) == (412, 18, job.id)
    assert row.cost_usd == Decimal("0"), "a plan call is covered by the plan"


def test_fr32_the_state_follows_the_budget(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        limits.set_budget(session, CLAUDE, {"calls_5h": 5, "calls_7d": 50})
        states = []
        for _ in range(5):
            used(session, CLAUDE, ago=timedelta(minutes=1))
            states.append(limits.refresh(session, CLAUDE, now=NOW).state)
        source = limits.refresh(session, CLAUDE, now=NOW).source

    ok, near, paused = ProviderState.OK, ProviderState.NEAR_BUDGET, ProviderState.PAUSED_BY_BUDGET
    assert states == [ok, ok, ok, near, paused]
    assert source is StatusSource.APP, "a budget state is this app's own count"


def test_fr32_a_paused_provider_works_again_when_the_window_moves_on(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        limits.set_budget(session, CLAUDE, {"calls_5h": 1, "calls_7d": 50})
        used(session, CLAUDE, ago=timedelta(hours=4))

        assert limits.gate(session, CLAUDE, episode_id=None, now=NOW) is not None
        assert limits.gate(session, CLAUDE, episode_id=None, now=NOW + timedelta(hours=2)) is None


def test_fr32_continue_anyway_lets_one_episode_through_a_budget_pause(
    sessions: sessionmaker[Session],
) -> None:
    mine, other = uuid.uuid4(), uuid.uuid4()
    with sessions.begin() as session:
        limits.set_budget(session, CLAUDE, {"calls_5h": 0, "calls_7d": 0})
        used(session, CLAUDE, ago=timedelta(minutes=1))
        limits.allow_episode(session, CLAUDE, mine)

        assert limits.gate(session, CLAUDE, episode_id=mine, now=NOW) is None
        assert limits.gate(session, CLAUDE, episode_id=other, now=NOW) is not None
        assert limits.gate(session, CLAUDE, episode_id=None, now=NOW) is not None
        # The override is for the provider it was given for.
        limits.set_budget(session, CHATGPT, {"calls_5h": 0, "calls_7d": 0})
        used(session, CHATGPT, ago=timedelta(minutes=1))
        assert limits.gate(session, CHATGPT, episode_id=mine, now=NOW) is not None


def test_fr31_a_limit_event_limits_the_provider_until_the_reset_time(
    sessions: sessionmaker[Session],
) -> None:
    until = NOW + timedelta(hours=2)
    with sessions.begin() as session:
        limits.limit_reached(
            session, CLAUDE, message="You've hit your session limit", retry_at=until, now=NOW
        )
        waiting = limits.gate(session, CLAUDE, episode_id=None, now=NOW)
        row = limits.refresh(session, CLAUDE, now=NOW)

    assert waiting is not None
    assert waiting[1] == until
    assert (row.state, row.source) == (ProviderState.LIMITED, StatusSource.TOOL)
    assert row.last_error == "You've hit your session limit"


def test_fr31_continue_anyway_cannot_lift_a_limit(sessions: sessionmaker[Session]) -> None:
    episode = uuid.uuid4()
    with sessions.begin() as session:
        limits.limit_reached(session, CLAUDE, message="limit", retry_at=None, now=NOW)
        limits.allow_episode(session, CLAUDE, episode)

        assert limits.gate(session, CLAUDE, episode_id=episode, now=NOW) is not None


def test_fr34_a_routine_check_on_a_healthy_provider_makes_no_model_call(
    sessions: sessionmaker[Session],
) -> None:
    probe = FakeProbe()
    with sessions.begin() as session:
        views = limits.check(session, "subscription", probe, now=NOW)

    assert probe.free == [CLAUDE, CHATGPT]
    assert probe.called == []
    assert [view.state for view in views] == [ProviderState.OK, ProviderState.OK]
    assert all(view.last_checked_at == NOW for view in views)


def test_fr34_demo_mode_has_nothing_to_check(sessions: sessionmaker[Session]) -> None:
    probe = FakeProbe()
    with sessions.begin() as session:
        views = limits.check(session, "demo", probe, now=NOW)

    assert (probe.free, probe.called) == ([], [])
    assert [view.provider for view in views] == [Provider.DEMO]


def test_fr34_a_limit_with_a_reset_time_ahead_is_not_probed(
    sessions: sessionmaker[Session],
) -> None:
    probe = FakeProbe()
    with sessions.begin() as session:
        limits.limit_reached(
            session, CLAUDE, message="limit", retry_at=NOW + timedelta(hours=1), now=NOW
        )
        views = limits.check(session, "subscription", probe, now=NOW + timedelta(minutes=10))

    assert probe.called == []
    assert views[0].state is ProviderState.LIMITED


@pytest.mark.parametrize("retry_at", [None, NOW + timedelta(minutes=5)])
def test_fr34_a_limit_without_a_time_or_past_its_time_is_probed_and_lifted(
    sessions: sessionmaker[Session], retry_at: datetime | None
) -> None:
    probe = FakeProbe()
    with sessions.begin() as session:
        limits.limit_reached(session, CLAUDE, message="limit", retry_at=retry_at, now=NOW)
        views = limits.check(session, "subscription", probe, now=NOW + timedelta(minutes=10))

    assert probe.called == [CLAUDE], "only the limited provider gets the tiny call"
    assert views[0].state is ProviderState.OK
    assert (views[0].limited_until, views[0].last_error) == (None, None)


def test_fr34_a_probe_that_meets_the_limit_again_keeps_the_provider_limited(
    sessions: sessionmaker[Session],
) -> None:
    again = NOW + timedelta(hours=3)
    probe = FakeProbe(call=PlanLimitError("still limited", retry_at=again))
    with sessions.begin() as session:
        limits.limit_reached(session, CLAUDE, message="limit", retry_at=None, now=NOW)
        views = limits.check(session, "subscription", probe, now=NOW + timedelta(minutes=10))

    assert views[0].state is ProviderState.LIMITED
    assert (views[0].limited_until, views[0].last_error) == (again, "still limited")


def test_fr34_a_probe_that_cannot_be_made_changes_nothing_but_the_note(
    sessions: sessionmaker[Session],
) -> None:
    probe = FakeProbe(call=RetryableError("the bridge is busy"))
    with sessions.begin() as session:
        limits.limit_reached(session, CLAUDE, message="limit", retry_at=None, now=NOW)
        views = limits.check(session, "subscription", probe, now=NOW + timedelta(minutes=10))

    assert views[0].state is ProviderState.LIMITED
    assert views[0].last_error == "the bridge is busy"


def test_fr34_a_tool_that_is_signed_out_is_noted_and_not_probed(
    sessions: sessionmaker[Session],
) -> None:
    probe = FakeProbe(problem="Claude Code is not signed in.")
    with sessions.begin() as session:
        limits.limit_reached(session, CLAUDE, message="limit", retry_at=None, now=NOW)
        views = limits.check(session, "subscription", probe, now=NOW + timedelta(minutes=10))

    assert probe.called == []
    assert views[0].last_error == "Claude Code is not signed in."
    assert views[1].last_error == "Claude Code is not signed in."


def test_fr34_check_now_probes_a_limited_provider_even_before_its_reset_time(
    sessions: sessionmaker[Session],
) -> None:
    probe = FakeProbe()
    with sessions.begin() as session:
        limits.limit_reached(
            session, CLAUDE, message="limit", retry_at=NOW + timedelta(hours=4), now=NOW
        )
        views = limits.check(session, "subscription", probe, now=NOW, on_demand=True)

    assert probe.called == [CLAUDE]
    assert views[0].state is ProviderState.OK


def test_fr34_check_now_runs_at_most_once_in_30_seconds(sessions: sessionmaker[Session]) -> None:
    probe = FakeProbe()
    with sessions.begin() as session:
        limits.check(session, "subscription", probe, now=NOW, on_demand=True)
        with pytest.raises(limits.CheckTooSoonError) as raised:
            limits.check(
                session, "subscription", probe, now=NOW + timedelta(seconds=10), on_demand=True
            )
        # The automatic check is not held back by it, and after 30 seconds it runs again.
        limits.check(session, "subscription", probe, now=NOW + timedelta(seconds=11))
        limits.check(
            session, "subscription", probe, now=NOW + timedelta(seconds=31), on_demand=True
        )

    assert raised.value.wait_s == 20


def test_fr34_a_check_never_resets_the_budget_count(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        limits.set_budget(session, CLAUDE, {"calls_5h": 1, "calls_7d": 50})
        used(session, CLAUDE, ago=timedelta(minutes=1))
        views = limits.check(session, "subscription", FakeProbe(), now=NOW, on_demand=True)

    assert views[0].state is ProviderState.PAUSED_BY_BUDGET
    assert views[0].usage.five_hours.calls == 1
    assert views[0].share == pytest.approx(1.0)


def waiting_job(session: Session, job_type: str, episode_id: uuid.UUID | None = None) -> uuid.UUID:
    """A job that was put back in the queue to wait for a plan, as the worker does."""
    job = queue.enqueue(session, job_type=job_type, tag=JobTag.CPU)
    job.episode_id = episode_id
    claim = queue.claim_next(session, JobTag.CPU)
    assert claim is not None
    queue.fail(session, claim, ErrorClass.PLAN_LIMIT, "waiting", retry_at=NOW + timedelta(days=300))
    return job.id


def due(session: Session, job_id: uuid.UUID) -> bool:
    job = session.get(models.Job, job_id)
    assert job is not None
    session.refresh(job)
    return job.status is JobStatus.QUEUED and job.run_after <= datetime.now(UTC)


def test_fr34_lifting_a_limit_resumes_the_jobs_that_waited_for_that_provider(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        planner = waiting_job(session, "plan.brief")
        image = waiting_job(session, "gen.image")
        limits.limit_reached(session, CLAUDE, message="limit", retry_at=None, now=NOW)
        limits.check(session, "subscription", FakeProbe(), now=NOW + timedelta(minutes=10))

        assert due(session, planner)
        assert not due(session, image), "the image job waits for the other plan"


def test_the_overview_lists_each_provider_of_the_mode_once(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        subscription = limits.snapshot(session, "subscription", now=NOW)
        api = limits.snapshot(session, "api", now=NOW)

    assert [view.provider for view in subscription] == [CLAUDE, CHATGPT]
    assert [view.provider for view in api] == [Provider.ANTHROPIC_API, Provider.OPENAI_API]
    assert subscription[0].budget == limits.default_budget(CLAUDE)
    assert subscription[0].title == "Claude plan"
