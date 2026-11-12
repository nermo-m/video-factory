"""`POST /codex/image`: one picture from Codex's image tool (section 3.4, FR-30).

The tool is a fake program that saves a picture the way the real one does: below its own
home, in a folder named after the session. No test can spend plan usage.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import pytest

from tools.cli_bridge import codex
from tools.cli_bridge.contract import ImageRequest, parse_image_request
from tools.cli_bridge.errors import BridgeError
from tools.cli_bridge.tests.support import PLANTED, after, bridge, calls, fake

ROOT = Path(__file__).resolve().parents[3]
PICTURE = ROOT / "samples" / "lighthouse_keeper" / "assets" / "a_storm_sea.png"
SESSION = "00000000-0000-7000-8000-0000000000a1"
PROMPT = "A small harbour at first light, flat paper-cut shapes."


def environ(home: Path | None) -> dict[str, str]:
    cleaned = {name: value for name, value in os.environ.items() if name.upper() != "CODEX_HOME"}
    planted = {"OPENAI_API_KEY": PLANTED, "CODEX_API_KEY": PLANTED}
    return {**cleaned, **planted, **({"CODEX_HOME": str(home)} if home else {})}


def make(
    tmp_path: Path,
    *,
    output: str = "codex_image.jsonl",
    picture: Path | None = PICTURE,
    known_home: bool = True,
    announce: bool = False,
    **fields: Any,
) -> tuple[dict[str, Any], Path, Path]:
    """One picture call through the fake tool. Returns the answer, the record and the home."""
    home = tmp_path / "codex-home"
    record = tmp_path / "record.jsonl"
    tool = fake(
        "codex",
        output=output,
        record=record,
        image=picture,
        image_home=home,
        announce=announce,
    )
    studio = bridge(codex=tool, environ=environ(home if known_home else None))
    return studio.codex_image(ImageRequest(prompt=PROMPT, **fields)), record, home


def test_fr30_the_picture_the_tool_saved_comes_back_whole(tmp_path: Path) -> None:
    answer, _, _ = make(tmp_path)

    assert base64.b64decode(answer["image_base64"]) == PICTURE.read_bytes()
    assert (answer["media_type"], answer["bytes"]) == ("image/png", PICTURE.stat().st_size)
    assert (answer["tool"], answer["billing"], answer["turns"]) == ("codex", "plan", 1)
    assert answer["usage"] == {
        "input_tokens": 49442,
        "cached_input_tokens": 41088,
        "output_tokens": 401,
    }
    assert "text" not in answer, "what the model wrote is not passed on"


def test_fr30_the_picture_is_moved_out_of_the_tools_folder(tmp_path: Path) -> None:
    _, _, home = make(tmp_path)

    assert not (home / "generated_images" / SESSION).exists()


def test_the_image_tool_is_the_only_thing_switched_on(tmp_path: Path) -> None:
    _, record, _ = make(tmp_path, model="gpt-5.5")

    (run,) = calls(record)
    argv = run["argv"]
    disabled = [argv[index + 1] for index, value in enumerate(argv) if value == "--disable"]
    assert codex.IMAGE_FEATURE not in disabled
    assert sorted(disabled) == sorted(
        feature for feature in codex.DISABLED_FEATURES if feature != codex.IMAGE_FEATURE
    )
    assert after(argv, "--sandbox") == "read-only"
    assert {"--ephemeral", "--ignore-user-config", "--ignore-rules", "--strict-config"} <= set(argv)
    assert 'web_search="disabled"' in argv
    assert after(argv, "--model") == "gpt-5.5"
    assert argv[-1] == "-", "the prompt travels on standard input"


def test_the_prompt_asks_for_one_picture_and_carries_the_description(tmp_path: Path) -> None:
    _, record, _ = make(tmp_path)

    (run,) = calls(record)
    assert run["stdin"].startswith(codex.IMAGE_INSTRUCTION)
    assert run["stdin"].endswith(PROMPT)
    assert run["cwd_entries"] == [], "the tool works in an empty folder"


def test_fr27_no_key_reaches_the_tool_and_the_sign_in_is_checked_first(tmp_path: Path) -> None:
    _, record, home = make(tmp_path)

    (status,) = calls(record, "status")
    (run,) = calls(record)
    for entry in (status, run):
        assert PLANTED not in entry["env"].values()
        assert "OPENAI_API_KEY" not in entry["env"]
    assert run["env"]["CODEX_HOME"] == str(home)


def test_without_a_known_home_the_picture_is_found_through_the_path_the_tool_reports(
    tmp_path: Path,
) -> None:
    answer, _, home = make(tmp_path, known_home=False, announce=True)

    assert base64.b64decode(answer["image_base64"]) == PICTURE.read_bytes()
    assert not (home / "generated_images" / SESSION).exists()


def test_without_a_known_home_and_without_a_reported_path_there_is_no_picture(
    tmp_path: Path,
) -> None:
    with pytest.raises(BridgeError) as raised:
        make(tmp_path, known_home=False, announce=False)

    assert (raised.value.code, raised.value.status) == ("tool_failed", 502)


def test_a_reported_path_of_another_shape_is_never_opened(tmp_path: Path) -> None:
    """Only `.../generated_images/<this session>/<name>.png` is followed."""
    elsewhere = tmp_path / "private" / "generated_images" / "00000000-0000-7000-8000-0000000000ff"
    elsewhere.mkdir(parents=True)
    (elsewhere / "secret.png").write_bytes(PICTURE.read_bytes())
    run = codex._Run(
        thread_id=SESSION,
        messages=[
            str(elsewhere / "secret.png"),
            str(tmp_path / "private" / "secret.png"),
            f"{tmp_path}/generated_images/{SESSION}/../../private/x.png",
        ],
        usage={},
        turns=1,
    )

    assert codex._saved_pictures(run, None) == []
    assert (elsewhere / "secret.png").is_file()


def test_a_session_id_that_tries_to_leave_the_folder_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.png").write_bytes(PICTURE.read_bytes())

    with pytest.raises(BridgeError) as raised:
        make(tmp_path, output="codex_image_escape.jsonl", picture=None)

    assert raised.value.code == "tool_failed"
    assert (outside / "x.png").is_file()


def test_a_tool_that_creates_no_picture_fails_with_what_it_said(tmp_path: Path) -> None:
    with pytest.raises(BridgeError) as raised:
        make(tmp_path, output="codex_image_refused.jsonl", picture=None)

    assert (raised.value.code, raised.value.status) == ("tool_failed", 502)
    assert "without creating a picture" in str(raised.value)
    assert "logo" in str(raised.value)


def test_a_saved_file_that_is_not_a_png_is_refused(tmp_path: Path) -> None:
    not_a_picture = tmp_path / "text.png"
    not_a_picture.write_text("not a picture", encoding="utf-8")

    with pytest.raises(BridgeError) as raised:
        make(tmp_path, picture=not_a_picture)

    assert raised.value.code == "tool_failed"
    assert "not a PNG" in str(raised.value)


def test_fr29_a_usage_limit_becomes_plan_limit_with_the_reset_time(tmp_path: Path) -> None:
    tool = fake("codex", output="codex_limit_today.jsonl", exit_code=1)
    studio = bridge(codex=tool, environ=environ(tmp_path))

    with pytest.raises(BridgeError) as raised:
        studio.codex_image(ImageRequest(prompt=PROMPT))

    assert (raised.value.code, raised.value.status) == ("plan_limit", 429)
    assert raised.value.retry_at is not None


def test_a_tool_that_is_signed_in_with_a_key_is_not_started(tmp_path: Path) -> None:
    record = tmp_path / "record.jsonl"
    tool = fake("codex", output="codex_image.jsonl", record=record, sign_in="api", image=PICTURE)
    studio = bridge(codex=tool, environ=environ(tmp_path))

    with pytest.raises(BridgeError) as raised:
        studio.codex_image(ImageRequest(prompt=PROMPT))

    assert raised.value.code == "not_plan_sign_in"
    assert calls(record) == []


# --- the request ---------------------------------------------------------------------------


def test_a_picture_request_takes_a_prompt_a_model_and_a_time_limit() -> None:
    request = parse_image_request(
        {"prompt": PROMPT, "model": "gpt-5.5", "timeout_s": 300}, max_timeout_seconds=1800
    )

    assert request == ImageRequest(prompt=PROMPT, model="gpt-5.5", timeout_s=300.0)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"prompt": ""},
        {"prompt": "   "},
        {"prompt": 5},
        {"prompt": "x" * 20_001},
        {"prompt": PROMPT, "schema": {}},
        {"prompt": PROMPT, "system": "Be bold."},
        {"prompt": PROMPT, "model": "--dangerous"},
        {"prompt": PROMPT, "timeout_s": 5000},
        [PROMPT],
    ],
)
def test_a_picture_request_that_is_not_right_is_refused_before_the_tool_starts(
    body: object,
) -> None:
    with pytest.raises(BridgeError) as raised:
        parse_image_request(body, max_timeout_seconds=1800)

    assert raised.value.status == 400
