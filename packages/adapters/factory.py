"""Adapter factory: one place that picks implementations by provider mode (section 3.4).

Build it for each job from the settings and the owner's "Use paid APIs" switch as it is
at that moment. The mode comes from the settings and is never changed here: there is no
fallback from one mode to another.

So far it knows the adapters that exist: storage and voice, which are local in every
mode, and the language model. The image adapter is added by its own card.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from packages.adapters.llm import AnthropicLLM, LLMAdapter, RecordedLLM
from packages.adapters.llm.anthropic_api import DEFAULT_MODEL
from packages.adapters.storage import LocalStorage
from packages.adapters.tts import TTSAdapter, create_tts_adapter
from packages.core.providers import (
    ModeProviders,
    PaidApiRefusedError,
    ensure_paid_apis_allowed,
    providers_for,
)
from packages.core.queue import NeedsOwnerError
from packages.core.settings import Settings

# Recorded answers of the planning skills for the sample episode (demo mode).
RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "samples" / "recordings"


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

    def llm(self) -> LLMAdapter:
        """The language model of the configured mode. Raises NeedsOwnerError when that
        mode cannot be served, and never reaches for another mode instead."""
        mode = self.settings.provider_mode
        if mode == "demo":
            return RecordedLLM(RECORDINGS_DIR)
        if mode == "subscription":
            raise NeedsOwnerError(
                "Subscription mode reaches its models through the host bridge, which is not "
                "built yet. Use PROVIDER_MODE=demo until it is."
            )
        try:
            return AnthropicLLM(
                mode=mode,
                paid_apis_confirmed=self.paid_apis_confirmed,
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
                model=os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL,
            )
        except PaidApiRefusedError as refused:
            raise NeedsOwnerError(str(refused)) from refused

    def storage(self) -> LocalStorage:
        return LocalStorage(self.settings.data_dir)

    def tts(self) -> TTSAdapter:
        return create_tts_adapter(
            Path(self.settings.kokoro_model_path), Path(self.settings.kokoro_voices_path)
        )
