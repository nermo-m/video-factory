"""Adapter factory: one place that picks implementations by provider mode (section 3.4).

Build it for each job from the settings and the owner's "Use paid APIs" switch as it is
at that moment. The mode comes from the settings and is never changed here: there is no
fallback from one mode to another.

So far it knows the adapters that exist: storage and voice, which are local in every
mode. The language model and image adapters are added by their own cards and choose by
`providers`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packages.adapters.storage import LocalStorage
from packages.adapters.tts import TTSAdapter, create_tts_adapter
from packages.core.providers import ModeProviders, ensure_paid_apis_allowed, providers_for
from packages.core.settings import Settings


@dataclass(frozen=True)
class Adapters:
    settings: Settings
    paid_apis_confirmed: bool = False

    @property
    def providers(self) -> ModeProviders:
        """Who answers text, second-opinion and image requests in the configured mode."""
        return providers_for(self.settings.provider_mode)

    def ensure_paid_apis(self) -> None:
        """Raise PaidApiRefusedError unless paid APIs are switched on twice (FR-28)."""
        ensure_paid_apis_allowed(self.settings.provider_mode, confirmed=self.paid_apis_confirmed)

    def storage(self) -> LocalStorage:
        return LocalStorage(self.settings.data_dir)

    def tts(self) -> TTSAdapter:
        return create_tts_adapter(
            Path(self.settings.kokoro_model_path), Path(self.settings.kokoro_voices_path)
        )
