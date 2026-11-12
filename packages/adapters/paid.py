"""The base of every adapter that calls a paid API (design doc section 3.4, FR-28).

"API adapters refuse to start and say why." The refusal is this class's constructor, so a
paid adapter that the owner has not switched on twice does not exist, and what does not
exist cannot make a call. A structural test (tests/infra/test_provider_mode.py) fails when
a module imports a paid SDK without building on this class.

Build a paid adapter for each job, never once at start-up: the owner can turn the Settings
switch off at any time, and the next job must see that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from packages.core.enums import Billing, Provider
from packages.core.providers import PaidApiRefusedError, billing_of, ensure_paid_apis_allowed


class PaidApiAdapter:
    provider: ClassVar[Provider]
    # The environment variable that holds this provider's key, named in messages.
    key_variable: ClassVar[str]

    def __init__(self, *, mode: str, paid_apis_confirmed: bool, api_key: str | None) -> None:
        if billing_of(self.provider) is not Billing.API:
            raise TypeError(
                f"{type(self).__name__} is a paid adapter but its provider "
                f"'{self.provider.value}' is not a paid API."
            )
        ensure_paid_apis_allowed(mode, confirmed=paid_apis_confirmed)
        if not (api_key or "").strip():
            raise PaidApiRefusedError(
                f"{self.key_variable} is not set. Put the key into .env and restart."
            )
        secret = (api_key or "").strip()
        # The key is held by this function, not in an attribute, so printing the adapter
        # or its attributes can never put it into a log (NFR-01).
        self._key: Callable[[], str] = lambda: secret

    def __repr__(self) -> str:
        return f"{type(self).__name__}(provider={self.provider.value!r})"
