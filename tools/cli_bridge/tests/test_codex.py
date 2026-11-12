"""`POST /codex`: one call to the Codex command line tool (section 3.4, FR-27).

As in test_claude.py the tool is a fake program, so no test can spend plan usage, and two
calls (`plain`, `structured`) are made once for the whole file.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tools.cli_bridge.contract import CodexRequest
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
    "properties": {"score": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
    "additionalProperties": False,
}
PROMPT = 'Review — "this" script,\nplease.'
ENVIRON = {
    **os.environ,
    "OPENAI_API_KEY": PLANTED,
    "CODEX_API_KEY": PLANTED,
    "OPENAI_BASE_URL": "https://paid.example/v1",
    "CODEX_HOME": "/home/someone/codex-home",
}


def ask(prompt: str = "Review this script.", **fields: Any) -> CodexRequest:
    return CodexRequest(prompt=prompt, **fields)


def call(tmp_path: Path, request: CodexRequest, output: str) -> Exchange:
    return exchange(
        "codex", tmp_path, lambda studio: studio.codex(request), output, environ=ENVIRON
    )


@pytest.fixture(scope="module")
def plain(tmp_path_factory: pytest.TempPathFactory) -> Exchange:
    """The smallest call: a prompt, nothing else."""
    return call(tmp_path_factory.mktemp("plain"), ask(PROMPT), "codex_text.jsonl")


@pytest.fixture(scope="module")
def structured(tmp_path_factory: pytest.TempPathFactory) -> Exchange:
    """A call with everything a request can carry."""
    request = ask(
        "Review this script.",
        system="You are a strict reviewer.",
        schema=SCHEMA,
        model="gpt-5.5",
        effort="high",
    )
    return call(tmp_path_factory.mktemp("structured"), request, "codex_structured.jsonl")


def values(argv: list[str], flag: str) -> list[str]:
    """Every value given with a flag that may be repeated."""
    return [argv[index + 1] for index, value in enumerate(argv) if value == flag]


def test_a_call_returns_the_final_message_with_its_numbers(plain: Exchange) -> None:
    answer = plain.answer

    assert answer["tool"] == "codex"
    assert answer["text"] == "The hook is strong, the ending is flat."
    assert answer["output"] is None
    assert answer["billing"] == "plan"
    assert answer["usage"] == {
        "input_tokens": 2400,
        "cached_input_tokens": 1800,
        "output_tokens": 52,
    }
    assert answer["duration_ms"] >= 0


def test_the_model_is_the_one_that_was_asked_for_or_unknown(
    plain: Exchange, structured: Exchange
) -> None:
    assert plain.answer["model"] is None
    assert structured.answer["model"] == "gpt-5.5"


def test_the_prompt_travels_on_standard_input(plain: Exchange) -> None:
    assert plain.run["stdin"] == PROMPT
    assert plain.run["argv"][-1] == "-", "a single dash tells the tool to read standard input"
    assert not any("Review" in argument for argument in plain.run["argv"])


def test_a_system_text_is_put_in_front_of_the_prompt(structured: Exchange) -> None:
    assert structured.run["stdin"] == "You are a strict reviewer.\n\nReview this script."


def test_the_tool_runs_non_interactively_in_the_read_only_sandbox(plain: Exchange) -> None:
    argv = plain.run["argv"]

    assert argv[0] == "exec"
    assert "--json" in argv
    assert after(argv, "--sandbox") == "read-only"
    assert after(argv, "--color") == "never"
    assert "--ephemeral" in argv
    assert "--skip-git-repo-check" in argv


def test_no_user_configuration_or_rules_are_picked_up(plain: Exchange) -> None:
    argv = plain.run["argv"]

    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    # An option this version does not know stops the call instead of being ignored.
    assert "--strict-config" in argv


@pytest.mark.parametrize(
    "feature",
    [
        "shell_tool",
        "image_generation",
        "apps",
        "plugins",
        "multi_agent",
        "browser_use",
        "computer_use",
        "hooks",
    ],
)
def test_tools_are_switched_off(plain: Exchange, structured: Exchange, feature: str) -> None:
    for made in (plain, structured):
        assert feature in values(made.run["argv"], "--disable")
        assert "--enable" not in made.run["argv"]


def test_web_search_is_switched_off(plain: Exchange, structured: Exchange) -> None:
    for made in (plain, structured):
        assert 'web_search="disabled"' in values(made.run["argv"], "--config")


def test_the_sandbox_is_never_bypassed(plain: Exchange, structured: Exchange) -> None:
    for made in (plain, structured):
        argv = made.run["argv"]
        assert "--dangerously-bypass-approvals-and-sandbox" not in argv
        assert "danger-full-access" not in argv
        assert "workspace-write" not in argv


@pytest.mark.parametrize("made", ["plain", "structured"])
def test_each_call_runs_in_an_empty_temporary_folder(
    made: str, request: pytest.FixtureRequest
) -> None:
    run = request.getfixturevalue(made).run

    folder = Path(run["cwd"]).resolve()
    assert run["cwd_entries"] == []
    assert Path(after(run["argv"], "--cd")).resolve() == folder
    assert ROOT not in (folder, *folder.parents), "no project file may be in reach"
    assert not folder.exists(), "the folder is removed after the call"


def test_a_schema_goes_in_a_file_and_the_answer_is_parsed(structured: Exchange) -> None:
    file = after(structured.run["argv"], "--output-schema")

    assert json.loads(structured.run["files"][file]) == SCHEMA
    assert Path(file).parent != Path(structured.run["cwd"])
    assert structured.answer["output"] == {"score": 7, "reason": "Clear, a little slow."}


def test_an_answer_that_ignores_the_schema_is_invalid_output() -> None:
    tool = fake("codex", output="codex_schema_missing.jsonl")

    with pytest.raises(BridgeError) as raised:
        bridge(codex=tool).codex(ask(schema=SCHEMA))

    assert raised.value.code == "invalid_output"


def test_model_and_effort_are_passed_only_when_asked_for(
    plain: Exchange, structured: Exchange
) -> None:
    assert "--model" not in plain.run["argv"]
    assert "--output-schema" not in plain.run["argv"]
    assert not any("model_reasoning_effort" in argument for argument in plain.run["argv"])
    assert after(structured.run["argv"], "--model") == "gpt-5.5"
    assert 'model_reasoning_effort="high"' in values(structured.run["argv"], "--config")


def test_fr27_key_variables_do_not_reach_the_tool(plain: Exchange) -> None:
    for given in (plain.status, plain.run):
        assert PLANTED not in json.dumps(given["env"])
        assert "OPENAI_BASE_URL" not in given["env"]
        assert given["env"]["CODEX_HOME"] == "/home/someone/codex-home"


def test_fr27_the_sign_in_is_checked_before_every_call(plain: Exchange) -> None:
    assert plain.status["argv"] == ["login", "status"]


def test_fr29_a_usage_limit_becomes_plan_limit_with_the_reset_time() -> None:
    tool = fake("codex", output="codex_limit_today.jsonl", exit_code=1)

    with pytest.raises(BridgeError) as raised:
        bridge(codex=tool).codex(ask())

    assert raised.value.code == "plan_limit"
    assert raised.value.retry_at == datetime(2026, 11, 12, 15, 15, tzinfo=ZONE)
    assert raised.value.tool == "codex"


def test_fr29_a_limit_that_resets_on_another_day_keeps_its_date() -> None:
    tool = fake("codex", output="codex_limit_later.jsonl", exit_code=1)

    with pytest.raises(BridgeError) as raised:
        bridge(codex=tool).codex(ask())

    assert raised.value.code == "plan_limit"
    assert raised.value.retry_at == datetime(2026, 11, 14, 9, 5, tzinfo=ZONE)


def test_fr29_a_limit_printed_as_plain_text_is_still_recognised() -> None:
    tool = fake(
        "codex",
        exit_code=1,
        stderr="ERROR: You've hit your usage limit. Try again at 3:15 PM.\n",
    )

    with pytest.raises(BridgeError) as raised:
        bridge(codex=tool).codex(ask())

    assert raised.value.code == "plan_limit"
    assert raised.value.retry_at == datetime(2026, 11, 12, 15, 15, tzinfo=ZONE)


def test_a_failed_turn_is_a_tool_failure_with_its_words() -> None:
    tool = fake("codex", output="codex_failed.jsonl", exit_code=1)

    with pytest.raises(BridgeError) as raised:
        bridge(codex=tool).codex(ask())

    assert raised.value.code == "tool_failed"
    assert "stream disconnected" in raised.value.message


def test_a_run_without_a_final_message_is_a_tool_failure() -> None:
    with pytest.raises(BridgeError) as raised:
        bridge(codex=fake("codex", output="codex_no_message.jsonl")).codex(ask())

    assert raised.value.code == "tool_failed"


def test_an_option_the_tool_does_not_know_is_a_tool_failure_with_its_words() -> None:
    tool = fake("codex", exit_code=1, stderr="Error: Unknown feature flag: shell_tool\n")

    with pytest.raises(BridgeError) as raised:
        bridge(codex=tool).codex(ask())

    assert raised.value.code == "tool_failed"
    assert "Unknown feature flag: shell_tool" in raised.value.message


def test_a_call_that_takes_too_long_is_stopped() -> None:
    tool = fake("codex", output="codex_text.jsonl", sleep=30)

    with pytest.raises(BridgeError) as raised:
        bridge(codex=tool).codex(ask(timeout_s=0.5))

    assert raised.value.code == "timeout"


def test_a_tool_that_is_not_installed_is_reported_as_such() -> None:
    with pytest.raises(BridgeError) as raised:
        bridge(codex=MISSING).codex(ask())

    assert raised.value.code == "not_installed"
    assert "CODEX_BIN" in raised.value.message


def test_a_tool_that_is_not_signed_in_is_not_started(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    tool = fake("codex", output="codex_text.jsonl", record=record, sign_in="none")

    with pytest.raises(BridgeError) as raised:
        bridge(codex=tool).codex(ask())

    assert raised.value.code == "not_signed_in"
    assert "codex login" in raised.value.message
    assert calls(record) == []


def test_fr28_a_tool_signed_in_with_an_api_key_is_not_started(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    tool = fake("codex", output="codex_text.jsonl", record=record, sign_in="api")

    with pytest.raises(BridgeError) as raised:
        bridge(codex=tool).codex(ask())

    assert raised.value.code == "not_plan_sign_in"
    assert calls(record) == [], "a call billed per use must never start"
