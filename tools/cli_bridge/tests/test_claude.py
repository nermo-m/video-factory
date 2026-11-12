"""`POST /claude`: one call to the Claude Code command line tool (section 3.4, FR-27).

The tool here is a fake program that prints recorded output and writes down what it was
given. No test starts the real tool, so no test can spend plan usage.

Starting a program takes a moment, most of all on Windows. Three calls are therefore made
once for the whole file (`plain`, `research`, `structured`) and many tests look at what
those calls were given and what they returned.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from packages.core import logs
from tools.cli_bridge.contract import ClaudeRequest, CodexRequest
from tools.cli_bridge.errors import BridgeError
from tools.cli_bridge.tests.support import (
    MISSING,
    PLANTED,
    ZONE,
    Exchange,
    after,
    bridge,
    calls,
    exchange,
    fake,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = {
    "type": "object",
    "properties": {"lesson": {"type": "string"}, "beats": {"type": "integer"}},
    "required": ["lesson", "beats"],
    "additionalProperties": False,
}
PROMPT = 'An idea — with "quotes", a % sign and\ntwo lines.'
SYSTEM = "You plan short videos.\nBe brief."
ENVIRON = {
    **os.environ,
    "ANTHROPIC_API_KEY": PLANTED,
    "ANTHROPIC_AUTH_TOKEN": PLANTED,
    "OPENAI_API_KEY": PLANTED,
    "CODEX_API_KEY": PLANTED,
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "HARMLESS": "kept",
}


def ask(prompt: str = "An idea about a lighthouse keeper.", **fields: Any) -> ClaudeRequest:
    return ClaudeRequest(prompt=prompt, **fields)


def call(tmp_path: Path, request: ClaudeRequest, output: str) -> Exchange:
    return exchange(
        "claude", tmp_path, lambda studio: studio.claude(request), output, environ=ENVIRON
    )


@pytest.fixture(scope="module")
def plain(tmp_path_factory: pytest.TempPathFactory) -> Exchange:
    """The smallest call: a prompt, nothing else."""
    return call(tmp_path_factory.mktemp("plain"), ask(PROMPT), "claude_text.jsonl")


@pytest.fixture(scope="module")
def research(tmp_path_factory: pytest.TempPathFactory) -> Exchange:
    """A call that may search the web."""
    return call(tmp_path_factory.mktemp("research"), ask(web_search=True), "claude_search.jsonl")


@pytest.fixture(scope="module")
def structured(tmp_path_factory: pytest.TempPathFactory) -> Exchange:
    """A call with everything a request can carry."""
    request = ask(
        system=SYSTEM, schema=SCHEMA, model="claude-sonnet-5-5", effort="low", max_turns=2
    )
    return call(tmp_path_factory.mktemp("structured"), request, "claude_structured.jsonl")


def test_a_call_returns_the_answer_with_its_numbers(plain: Exchange) -> None:
    answer = plain.answer

    assert answer["tool"] == "claude"
    assert answer["text"] == "A lighthouse keeper counts the ships he brought home."
    assert answer["output"] is None
    assert answer["billing"] == "plan"
    assert answer["turns"] == 1
    assert answer["searches"] == 0
    assert answer["tool_duration_ms"] == 2310
    assert answer["duration_ms"] >= 0


def test_the_model_that_wrote_the_answer_is_reported_not_a_helper_model(plain: Exchange) -> None:
    assert plain.answer["model"] == "claude-opus-5-5"


def test_input_tokens_count_everything_the_model_read(plain: Exchange) -> None:
    # 12 new, 300 written to the cache and 100 read from it.
    assert plain.answer["usage"] == {
        "input_tokens": 412,
        "cached_input_tokens": 100,
        "output_tokens": 18,
    }


def test_the_prompt_travels_on_standard_input_and_not_on_the_command_line(
    plain: Exchange,
) -> None:
    assert plain.run["stdin"] == PROMPT
    assert not any("An idea" in argument for argument in plain.run["argv"])


def test_the_tool_is_asked_for_one_json_result_without_a_session(plain: Exchange) -> None:
    argv = plain.run["argv"]

    assert argv[0] == "-p"
    assert after(argv, "--output-format") == "stream-json"
    assert "--verbose" in argv
    assert "--no-session-persistence" in argv


def test_no_settings_plugins_or_project_files_are_picked_up(plain: Exchange) -> None:
    argv = plain.run["argv"]

    assert "--safe-mode" in argv
    assert after(argv, "--setting-sources") == ""
    assert "--strict-mcp-config" in argv
    assert "--disable-slash-commands" in argv


def test_tools_are_switched_off_by_default(plain: Exchange) -> None:
    argv = plain.run["argv"]

    assert after(argv, "--tools") == ""
    assert "--allowed-tools" not in argv
    assert after(argv, "--permission-prompts") == "none"


def test_a_research_call_gets_web_search_and_fetch_and_nothing_else(research: Exchange) -> None:
    argv = research.run["argv"]

    assert after(argv, "--tools") == "WebSearch,WebFetch"
    assert after(argv, "--allowed-tools") == "WebSearch,WebFetch"


def test_searches_are_counted(research: Exchange) -> None:
    assert research.answer["searches"] == 3
    assert research.answer["turns"] == 5


@pytest.mark.parametrize(
    "flag",
    ["--bare", "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions"],
)
def test_flags_that_would_change_billing_or_safety_are_never_passed(
    plain: Exchange, research: Exchange, structured: Exchange, flag: str
) -> None:
    # --bare makes the tool use an API key only, which is the opposite of this bridge.
    for made in (plain, research, structured):
        assert flag not in made.run["argv"]


def test_a_turn_limit_is_always_set(
    plain: Exchange, research: Exchange, structured: Exchange
) -> None:
    turns = int(after(plain.run["argv"], "--max-turns"))

    assert turns >= 1
    assert int(after(research.run["argv"], "--max-turns")) > turns
    assert after(structured.run["argv"], "--max-turns") == "2"


def test_a_schema_is_passed_on_and_the_structured_answer_comes_back(
    structured: Exchange,
) -> None:
    assert json.loads(after(structured.run["argv"], "--json-schema")) == SCHEMA
    assert structured.answer["output"] == {"lesson": "Small lights matter.", "beats": 3}


def test_a_structured_answer_given_as_text_is_still_read() -> None:
    tool = fake("claude", output="claude_schema_as_text.jsonl")

    answer = bridge(claude=tool).claude(ask(schema=SCHEMA))

    assert answer["output"] == {"lesson": "Small lights matter.", "beats": 3}


def test_an_answer_that_ignores_the_schema_is_invalid_output() -> None:
    tool = fake("claude", output="claude_schema_missing.jsonl")

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask(schema=SCHEMA))

    assert raised.value.code == "invalid_output"


def test_without_a_schema_no_schema_flag_is_passed(plain: Exchange) -> None:
    assert "--json-schema" not in plain.run["argv"]


def test_the_system_prompt_goes_in_a_file_outside_the_working_folder(
    structured: Exchange,
) -> None:
    file = after(structured.run["argv"], "--system-prompt-file")

    assert structured.run["files"][file] == SYSTEM
    assert Path(file).parent != Path(structured.run["cwd"])
    assert not Path(file).exists(), "the file is removed after the call"


def test_without_a_system_prompt_no_file_is_passed(plain: Exchange) -> None:
    assert "--system-prompt-file" not in plain.run["argv"]


def test_model_and_effort_are_passed_only_when_asked_for(
    plain: Exchange, structured: Exchange
) -> None:
    assert "--model" not in plain.run["argv"]
    assert "--effort" not in plain.run["argv"]
    assert after(structured.run["argv"], "--model") == "claude-sonnet-5-5"
    assert after(structured.run["argv"], "--effort") == "low"


@pytest.mark.parametrize("made", ["plain", "structured"])
def test_each_call_runs_in_an_empty_temporary_folder(
    made: str, request: pytest.FixtureRequest
) -> None:
    run = request.getfixturevalue(made).run

    folder = Path(run["cwd"]).resolve()
    assert run["cwd_entries"] == []
    assert ROOT not in (folder, *folder.parents), "no project file may be in reach"
    assert not folder.exists(), "the folder is removed after the call"


def test_fr27_key_variables_do_not_reach_the_tool(plain: Exchange) -> None:
    for given in (plain.status, plain.run):
        assert PLANTED not in json.dumps(given["env"])
        assert "CLAUDE_CODE_USE_BEDROCK" not in given["env"]
        assert given["env"]["HARMLESS"] == "kept"


def test_fr27_the_sign_in_is_checked_before_every_call(plain: Exchange) -> None:
    assert plain.status["argv"] == ["auth", "status", "--json"]


def test_fr29_a_session_limit_becomes_plan_limit_with_the_reset_time() -> None:
    tool = fake("claude", output="claude_limit_session.jsonl", exit_code=1)

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask())

    assert raised.value.code == "plan_limit"
    assert raised.value.retry_at == datetime(2026, 11, 12, 15, 0, tzinfo=ZONE)
    assert raised.value.tool == "claude"
    assert "session limit" in raised.value.message


def test_fr29_a_weekly_limit_becomes_plan_limit_with_its_date() -> None:
    tool = fake("claude", output="claude_limit_weekly.jsonl", exit_code=1)

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask())

    assert raised.value.code == "plan_limit"
    assert raised.value.retry_at == datetime(2026, 11, 14, 9, 0, tzinfo=ZONE)


def test_fr29_a_limit_printed_as_plain_text_is_still_recognised() -> None:
    tool = fake(
        "claude",
        exit_code=1,
        stderr="You've hit your session limit · resets 3pm (Europe/Sofia)\n",
    )

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask())

    assert raised.value.code == "plan_limit"
    assert raised.value.retry_at == datetime(2026, 11, 12, 15, 0, tzinfo=ZONE)


def test_an_answer_that_talks_about_limits_is_an_answer() -> None:
    answer = bridge(claude=fake("claude", output="claude_about_limits.jsonl")).claude(ask())

    assert "weekly limit" in answer["text"]


def test_running_out_of_turns_is_a_tool_failure_that_says_so() -> None:
    tool = fake("claude", output="claude_max_turns.jsonl", exit_code=1)

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask())

    assert raised.value.code == "tool_failed"
    assert "turn" in raised.value.message


def test_an_error_from_the_tool_is_a_tool_failure_with_its_words() -> None:
    tool = fake("claude", output="claude_error.jsonl", exit_code=1)

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask())

    assert raised.value.code == "tool_failed"
    assert "529 Overloaded" in raised.value.message


def test_output_that_is_not_json_is_a_tool_failure() -> None:
    with pytest.raises(BridgeError) as raised:
        bridge(claude=fake("claude", output="not_json.txt")).claude(ask())

    assert raised.value.code == "tool_failed"


def test_a_crash_is_a_tool_failure_with_the_end_of_its_error_output() -> None:
    tool = fake("claude", exit_code=3, stderr="error: unknown option '--safe-mode'\n")

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask())

    assert raised.value.code == "tool_failed"
    assert "unknown option '--safe-mode'" in raised.value.message
    assert "exit code 3" in raised.value.message


def test_a_call_that_takes_too_long_is_stopped() -> None:
    tool = fake("claude", output="claude_text.jsonl", sleep=30)
    started = time.monotonic()

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask(timeout_s=0.5))

    assert raised.value.code == "timeout"
    assert time.monotonic() - started < 15, "the tool is killed, not waited for"


def test_a_request_cannot_ask_for_more_time_than_the_bridge_allows() -> None:
    tool = fake("claude", output="claude_text.jsonl", sleep=30)

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool, max_timeout_seconds=0.5).claude(ask(timeout_s=600))

    assert raised.value.code == "timeout"


def test_a_tool_that_is_not_installed_is_reported_as_such() -> None:
    with pytest.raises(BridgeError) as raised:
        bridge(claude=MISSING).claude(ask())

    assert raised.value.code == "not_installed"
    assert "CLAUDE_BIN" in raised.value.message


def test_a_tool_that_is_not_signed_in_is_not_started(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    tool = fake("claude", output="claude_text.jsonl", record=record, sign_in="none")

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask())

    assert raised.value.code == "not_signed_in"
    assert "claude auth login" in raised.value.message
    assert calls(record) == []


def test_fr28_a_tool_signed_in_with_an_api_key_is_not_started(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    tool = fake("claude", output="claude_text.jsonl", record=record, sign_in="api")

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool).claude(ask())

    assert raised.value.code == "not_plan_sign_in"
    assert calls(record) == [], "a call billed per use must never start"


def test_a_tool_whose_status_check_hangs_is_not_started(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    tool = fake("claude", output="claude_text.jsonl", record=record, status_sleep=30)

    with pytest.raises(BridgeError) as raised:
        bridge(claude=tool, status_timeout_seconds=0.5).claude(ask())

    assert raised.value.code == "tool_failed"
    assert calls(record) == []


def wait_until_started(record: Path) -> None:
    deadline = time.monotonic() + 15
    while not calls(record) and time.monotonic() < deadline:
        time.sleep(0.05)


def test_one_call_at_a_time_and_the_second_one_waits_its_turn(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    studio = bridge(
        claude=fake("claude", output="claude_text.jsonl", record=record, sleep=0.6),
        queue_seconds=30,
    )
    answers: list[dict[str, Any]] = []
    threads = [
        threading.Thread(target=lambda: answers.append(studio.claude(ask()))) for _ in range(2)
    ]

    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(answers) == 2
    assert time.monotonic() - started >= 1.2, "the two calls ran one after the other"


def test_a_busy_tool_turns_away_a_call_that_waited_too_long_and_leaves_codex_free(
    tmp_path: Path,
) -> None:
    record = tmp_path / "record.jsonl"
    studio = bridge(
        claude=fake("claude", output="claude_text.jsonl", record=record, sleep=2.5),
        codex=fake("codex", output="codex_text.jsonl"),
        queue_seconds=0.1,
    )
    first = threading.Thread(target=lambda: studio.claude(ask()))
    first.start()
    wait_until_started(record)

    with pytest.raises(BridgeError) as raised:
        studio.claude(ask())
    other = studio.codex(CodexRequest(prompt="Review this."))
    first.join(timeout=30)

    assert raised.value.code == "busy"
    assert other["tool"] == "codex"


@pytest.fixture
def logged() -> Iterator[io.StringIO]:
    """Everything any logger writes during the test, at debug level."""
    stream = io.StringIO()
    root = logging.getLogger()
    before, level = root.handlers[:], root.level
    logs.configure_logging("debug", stream=stream)
    yield stream
    root.handlers[:] = before
    root.setLevel(level)


def test_nfr01_a_call_is_logged_with_numbers_and_without_its_text(logged: io.StringIO) -> None:
    studio = bridge(claude=fake("claude", output="claude_text.jsonl"), environ=ENVIRON)

    studio.claude(ask("A secret idea about habits.", system=SYSTEM))

    lines = [json.loads(line) for line in logged.getvalue().splitlines()]
    (entry,) = [line for line in lines if line["message"] == "bridge call"]
    assert entry["tool"] == "claude"
    assert entry["outcome"] == "ok"
    assert (entry["input_tokens"], entry["output_tokens"]) == (412, 18)
    everything = logged.getvalue()
    assert PLANTED not in everything
    assert "A secret idea" not in everything
    assert "You plan short videos." not in everything
    assert "lighthouse keeper counts" not in everything


def test_nfr01_a_failed_call_is_logged_with_its_error_class_only(logged: io.StringIO) -> None:
    tool = fake("claude", output="claude_limit_session.jsonl", exit_code=1)

    with pytest.raises(BridgeError):
        bridge(claude=tool).claude(ask("A secret idea about habits."))

    lines = [json.loads(line) for line in logged.getvalue().splitlines()]
    (entry,) = [line for line in lines if line["message"] == "bridge call"]
    assert entry["outcome"] == "plan_limit"
    assert "A secret idea" not in logged.getvalue()
