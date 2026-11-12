"""How the limits check looks at the real providers (section 3.5, FR-34).

* The free check asks the host bridge whether a tool is installed and signed in with a
  plan. It starts no model call and spends nothing.
* The tiny call is one very small model call through the same adapter the jobs use. The
  check makes it only for a provider that is limited, to see whether the limit is over.

Neither Claude Code nor Codex reports remaining quota in a form a program can read, so
there is nothing more to ask them (question Q-044).

Paid providers are never probed with a call: that would cost money, and a paid API has no
plan limit to wait out.
"""

from __future__ import annotations

import http.client
import json
import os
from urllib.parse import urlsplit

from packages.core.enums import Billing, Provider
from packages.core.providers import billing_of
from packages.core.settings import Settings

PROBE_PROMPT = "Reply with the single word: ok"
_TOOLS = {Provider.CLAUDE_PLAN: "claude", Provider.CHATGPT_PLAN: "codex"}
_KEYS = {Provider.ANTHROPIC_API: "ANTHROPIC_API_KEY", Provider.OPENAI_API: "OPENAI_API_KEY"}


class ProviderProbe:
    def __init__(self, settings: Settings, *, timeout_s: float = 30.0) -> None:
        self._settings = settings
        self._timeout_s = timeout_s

    def free_check(self, provider: Provider) -> str | None:
        """What stands in the way of using this provider, or None. Makes no model call."""
        billing = billing_of(provider)
        if billing is Billing.DEMO:
            return None
        if billing is Billing.API:
            name = _KEYS[provider]
            return None if os.environ.get(name, "").strip() else f"{name} is not set."
        url = self._settings.cli_bridge_url
        address = urlsplit(url)
        connect = (
            http.client.HTTPSConnection if address.scheme == "https" else http.client.HTTPConnection
        )
        connection = connect(address.hostname or "", address.port, timeout=self._timeout_s)
        try:
            connection.request("GET", f"{address.path.rstrip('/')}/health")
            health = json.loads(connection.getresponse().read())
            status = health["tools"][_TOOLS[provider]]
        except (OSError, http.client.HTTPException):
            return (
                f"The host bridge does not answer at {url}. Start it on the PC with "
                "`make bridge-start`."
            )
        except (ValueError, KeyError, TypeError):
            return f"What answers at {url} is not the bridge. Check CLI_BRIDGE_URL."
        finally:
            connection.close()
        if not isinstance(status, dict) or status.get("ready") is not True:
            message = status.get("message") if isinstance(status, dict) else None
            return message if isinstance(message, str) and message else "The tool is not ready."
        return None

    def tiny_call(self, provider: Provider) -> None:
        """One small call on a plan. Raises PlanLimitError while the limit still holds."""
        if billing_of(provider) is not Billing.PLAN:
            return
        # Imported here: the api service runs the check too and has no need for the other
        # language model adapters.
        from packages.adapters.llm.base import LLMRequest
        from packages.adapters.llm.cli_bridge import ClaudeCliLLM, CodexCliLLM

        adapter = ClaudeCliLLM if provider is Provider.CLAUDE_PLAN else CodexCliLLM
        model = (
            self._settings.claude_cli_model
            if provider is Provider.CLAUDE_PLAN
            else self._settings.codex_cli_model
        )
        adapter(
            mode=self._settings.provider_mode,
            bridge_url=self._settings.cli_bridge_url,
            model=model or None,
            timeout_s=120.0,
            queue_s=60.0,
        ).complete(
            LLMRequest(skill="limit_probe", skill_version="1", prompt=PROBE_PROMPT, effort="low")
        )
