"""The bridge reads what the real tools printed (card VFS-65).

The files in `recorded/live/` were captured on 2026-11-12 from Claude Code 2.1.300 and
Codex 0.144.1, run with the bridge's own command lines on the owner's plans. Session
numbers and everything about the PC were removed. Nothing else was changed, so these
tests fail when a reader stops understanding the tools' real output.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.cli_bridge import claude, codex
from tools.cli_bridge.contract import ClaudeRequest, CodexRequest
from tools.cli_bridge.errors import BridgeError
from tools.cli_bridge.process import Finished
from tools.cli_bridge.tests.support import NOW, RECORDED

LIVE = RECORDED / "live"
SCHEMA = {"type": "object"}


def printed(name: str, folder: Path = LIVE) -> Finished:
    return Finished(0, (folder / name).read_text(encoding="utf-8"), "", 0)


def test_a_real_claude_answer_is_read() -> None:
    answer = claude.read(printed("claude_text.jsonl"), ClaudeRequest(prompt="x"), now=NOW)

    assert answer["text"].startswith("Lighthouses guide ships safely")
    assert answer["model"] == "claude-opus-5-5"
    assert answer["usage"] == {
        "input_tokens": 2101,
        "cached_input_tokens": 649,
        "output_tokens": 49,
    }
    assert (answer["turns"], answer["searches"], answer["sources"]) == (1, 0, [])


def test_a_real_structured_claude_answer_is_read() -> None:
    answer = claude.read(
        printed("claude_structured.jsonl"), ClaudeRequest(prompt="x", schema=SCHEMA), now=NOW
    )

    assert answer["output"] == {
        "lesson": "Stand firm; your steady light guides others.",
        "beats": 3,
    }
    assert answer["turns"] == 2, "a structured answer takes a second turn"


def test_a_real_research_answer_names_the_sessions_model_not_the_search_helper() -> None:
    answer = claude.read(
        printed("claude_search.jsonl"), ClaudeRequest(prompt="x", web_search=True), now=NOW
    )

    # A smaller model reads the search results and writes more tokens than the session's
    # own model does. The session says which model it is.
    assert answer["model"] == "claude-opus-5-5"
    assert answer["searches"] == 1


def test_fr02_a_real_research_answer_comes_with_the_pages_the_search_returned() -> None:
    answer = claude.read(
        printed("claude_search.jsonl"), ClaudeRequest(prompt="x", web_search=True), now=NOW
    )

    sources = {source["url"]: source for source in answer["sources"]}
    wikipedia = sources["https://en.wikipedia.org/wiki/Smeaton%27s_Tower"]
    assert len(sources) >= 5
    assert wikipedia["title"] == "Smeaton%27s Tower"
    assert "1759" in wikipedia["text"], "the passage is what the search said about its results"


def test_fr02_a_real_fetched_page_is_a_source_with_what_was_read_from_it() -> None:
    answer = claude.read(
        printed("claude_fetch.jsonl"), ClaudeRequest(prompt="x", web_search=True), now=NOW
    )

    (source,) = answer["sources"]
    assert source["url"] == "https://en.wikipedia.org/wiki/Smeaton%27s_Tower"
    assert "16 October 1759" in source["text"]
    assert answer["searches"] == 0


def test_fr31_claude_code_reports_how_much_of_the_plan_is_used() -> None:
    answer = claude.read(printed("claude_search.jsonl"), ClaudeRequest(prompt="x"), now=NOW)

    assert answer["plan_usage"] == {
        "five_hour": {
            "used": 0.61,
            "resets_at": datetime.fromtimestamp(1794508200, UTC).isoformat(),
        },
        "seven_day": {
            "used": 0.05,
            "resets_at": datetime.fromtimestamp(1795096800, UTC).isoformat(),
        },
    }


def test_an_answer_without_a_usage_report_says_so() -> None:
    answer = claude.read(printed("claude_text.jsonl"), ClaudeRequest(prompt="x"), now=NOW)

    assert answer["plan_usage"] is None


def test_fr28_a_session_that_used_an_api_key_is_never_passed_off_as_a_plan_call() -> None:
    with pytest.raises(BridgeError) as raised:
        claude.read(
            printed("claude_api_key_session.jsonl", RECORDED), ClaudeRequest(prompt="x"), now=NOW
        )

    assert raised.value.code == "not_plan_sign_in"
    assert "API key" in raised.value.message


def test_fr29_a_limit_the_tool_reports_in_numbers_gives_the_exact_reset_time() -> None:
    finished = Finished(
        1, (RECORDED / "claude_limit_session.jsonl").read_text(encoding="utf-8"), "", 0
    )

    with pytest.raises(BridgeError) as raised:
        claude.read(finished, ClaudeRequest(prompt="x"), now=NOW.replace(hour=3))

    # Three in the morning: read from the sentence, "resets 3pm" would still be right,
    # but the number does not depend on the clock of this PC at all.
    assert raised.value.code == "plan_limit"
    assert raised.value.retry_at == datetime.fromtimestamp(1794488400, UTC)


def test_the_single_result_form_of_older_versions_is_still_read() -> None:
    last = (LIVE / "claude_text.jsonl").read_text(encoding="utf-8").splitlines()[-1]

    answer = claude.read(Finished(0, last, "", 0), ClaudeRequest(prompt="x"), now=NOW)

    assert answer["text"].startswith("Lighthouses guide ships safely")
    assert answer["model"] == "claude-opus-5-5"


def test_a_real_codex_answer_is_read() -> None:
    answer = codex.read(printed("codex_text.jsonl"), CodexRequest(prompt="x"), now=NOW)

    assert answer["text"] == "Lighthouses guide ships away from hazards and safely toward shore."
    assert answer["usage"] == {
        "input_tokens": 8687,
        "cached_input_tokens": 6016,
        "output_tokens": 17,
    }


def test_a_real_structured_codex_answer_is_read() -> None:
    # Codex accepted this project's kind of schema through its schema option on the day.
    answer = codex.read(
        printed("codex_structured.jsonl"), CodexRequest(prompt="x", schema=SCHEMA), now=NOW
    )

    assert answer["output"] == {
        "lesson": "Lighthouses guide sailors through darkness and danger.",
        "beats": 3,
    }
