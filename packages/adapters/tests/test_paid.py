"""Paid adapters refuse to start unless the owner has switched them on twice (FR-28).

"Keys present but mode not `api` means no API call is possible": an adapter that cannot be
built cannot call anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.adapters.factory import Adapters
from packages.adapters.paid import PaidApiAdapter
from packages.adapters.storage import LocalStorage
from packages.adapters.tts.samples import SampleVoice
from packages.core.enums import Provider
from packages.core.providers import PaidApiRefusedError
from packages.core.settings import Settings

PLANTED = "planted value, not a real key"
DATABASE_URL = "postgresql+psycopg://vfs:secret@db:5432/vfs"


class FakePaidAdapter(PaidApiAdapter):
    """Stands in for a real paid adapter. It records that it would have called out."""

    provider = Provider.ANTHROPIC_API
    key_variable = "ANTHROPIC_API_KEY"

    def call(self) -> str:
        return "a paid call was made"


@pytest.mark.parametrize("mode", ["demo", "subscription"])
@pytest.mark.parametrize("confirmed", [True, False])
def test_fr28_keys_present_but_another_mode_means_no_paid_adapter_exists(
    mode: str, confirmed: bool
) -> None:
    with pytest.raises(PaidApiRefusedError, match="PROVIDER_MODE"):
        FakePaidAdapter(mode=mode, paid_apis_confirmed=confirmed, api_key=PLANTED)


def test_fr28_api_mode_without_the_settings_switch_is_refused_too() -> None:
    with pytest.raises(PaidApiRefusedError, match="Use paid APIs"):
        FakePaidAdapter(mode="api", paid_apis_confirmed=False, api_key=PLANTED)


def test_with_mode_switch_and_key_the_adapter_starts() -> None:
    adapter = FakePaidAdapter(mode="api", paid_apis_confirmed=True, api_key=PLANTED)

    assert adapter.call() == "a paid call was made"


@pytest.mark.parametrize("key", [None, "", "   "])
def test_a_missing_key_is_named_by_its_variable(key: str | None) -> None:
    with pytest.raises(PaidApiRefusedError, match="ANTHROPIC_API_KEY is not set"):
        FakePaidAdapter(mode="api", paid_apis_confirmed=True, api_key=key)


def test_nfr01_the_key_never_shows_when_an_adapter_is_printed() -> None:
    adapter = FakePaidAdapter(mode="api", paid_apis_confirmed=True, api_key=PLANTED)

    assert PLANTED not in repr(adapter)
    assert PLANTED not in str(adapter)
    assert PLANTED not in str(vars(adapter))


def test_a_paid_adapter_must_belong_to_a_paid_provider() -> None:
    class Mislabelled(PaidApiAdapter):
        provider = Provider.CLAUDE_PLAN
        key_variable = "ANTHROPIC_API_KEY"

    with pytest.raises(TypeError, match="claude_plan"):
        Mislabelled(mode="api", paid_apis_confirmed=True, api_key=PLANTED)


# --- the factory -------------------------------------------------------------------------


def adapters(mode: str, *, confirmed: bool = False, data_dir: str = "/data") -> Adapters:
    settings = Settings(database_url=DATABASE_URL, provider_mode=mode, data_dir=data_dir)
    return Adapters(settings, paid_apis_confirmed=confirmed)


def test_the_factory_picks_providers_by_mode() -> None:
    assert adapters("demo").providers.text is Provider.DEMO
    assert adapters("subscription").providers.text is Provider.CLAUDE_PLAN
    assert adapters("api").providers.text is Provider.ANTHROPIC_API


def test_fr28_the_factory_refuses_paid_apis_like_the_adapters_do() -> None:
    adapters("api", confirmed=True).ensure_paid_apis()
    for mode, confirmed in (("api", False), ("subscription", True), ("demo", True)):
        with pytest.raises(PaidApiRefusedError):
            adapters(mode, confirmed=confirmed).ensure_paid_apis()


def test_storage_and_voice_are_local_in_every_mode(tmp_path: Path) -> None:
    for mode in ("demo", "subscription", "api"):
        chosen = adapters(mode, data_dir=str(tmp_path))

        assert isinstance(chosen.storage(), LocalStorage)
        # No voice model at the default path on this machine: the bundled recordings.
        assert isinstance(chosen.tts(), SampleVoice)
