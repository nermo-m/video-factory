"""The probe of the limits check, against a real bridge with fake tools (FR-34)."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from packages.adapters.limit_probe import PROBE_PROMPT, ProviderProbe
from packages.adapters.tests.test_llm_cli_bridge import bridge_with
from packages.core.enums import Provider
from packages.core.queue import PlanLimitError
from packages.core.settings import Settings
from tools.cli_bridge.tests.support import calls, fake

CLAUDE, CHATGPT = Provider.CLAUDE_PLAN, Provider.CHATGPT_PLAN
ROOT = Path(__file__).resolve().parents[3]


def probe(url: str, mode: str = "subscription") -> ProviderProbe:
    settings = Settings(
        database_url="postgresql+psycopg://vfs:secret@db:5432/vfs",
        provider_mode=mode,
        cli_bridge_url=url,
    )
    return ProviderProbe(settings, timeout_s=10)


def test_fr34_the_free_check_starts_no_model_call(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    tools = {
        "claude": fake("claude", output="claude_text.jsonl", record=record),
        "codex": fake("codex", output="codex_text.jsonl", record=record),
    }
    with bridge_with(**tools) as url:
        problems = [probe(url).free_check(provider) for provider in (CLAUDE, CHATGPT)]

    assert problems == [None, None]
    assert calls(record) == []


def test_fr34_the_free_check_says_what_the_owner_has_to_do(tmp_path: Path) -> None:
    with bridge_with(claude=fake("claude", sign_in="none")) as url:
        signed_out = probe(url).free_check(CLAUDE)
        missing = probe(url).free_check(CHATGPT)

    assert signed_out is not None
    assert "claude auth login" in signed_out
    assert missing is not None
    assert "CODEX_BIN" in missing


def test_fr34_a_bridge_that_is_not_running_is_reported_with_how_to_start_it() -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{taken.getsockname()[1]}"

    problem = probe(url).free_check(CLAUDE)

    assert problem is not None
    assert "make bridge-start" in problem


def test_fr34_the_tiny_call_is_one_small_call_to_the_right_tool(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    tools = {
        "claude": fake("claude", output="claude_text.jsonl", record=record),
        "codex": fake("codex", output="codex_text.jsonl", record=record),
    }
    with bridge_with(**tools) as url:
        probe(url).tiny_call(CHATGPT)

    (call,) = calls(record)
    assert call["argv"][0] == "exec"
    assert call["stdin"] == PROBE_PROMPT


def test_fr34_the_tiny_call_reports_a_limit_that_still_holds() -> None:
    tool = fake("claude", output="claude_limit_session.jsonl", exit_code=1)
    with bridge_with(claude=tool) as url, pytest.raises(PlanLimitError) as raised:
        probe(url).tiny_call(CLAUDE)

    assert raised.value.retry_at is not None


def test_fr28_a_paid_provider_is_never_probed_with_a_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "planted value, not a real key")
    checker = probe("http://127.0.0.1:9", mode="api")

    checker.tiny_call(Provider.ANTHROPIC_API)
    checker.tiny_call(Provider.DEMO)

    assert checker.free_check(Provider.ANTHROPIC_API) == "ANTHROPIC_API_KEY is not set."
    assert checker.free_check(Provider.OPENAI_API) is None
    assert checker.free_check(Provider.DEMO) is None


def test_the_api_service_can_load_the_probe_without_the_paid_sdk() -> None:
    """The api image does not install the worker's packages, such as `anthropic`."""
    code = (
        "import sys\n"
        "sys.modules['anthropic'] = None\n"
        "import packages.adapters.limit_probe\n"
        "from packages.adapters.llm.cli_bridge import ClaudeCliLLM\n"
        "print('loaded')\n"
    )
    done = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
    )

    assert done.stdout.strip() == "loaded", done.stderr[-500:]
