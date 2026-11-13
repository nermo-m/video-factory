"""The picture adapter of subscription mode (section 3.4, FR-28, FR-29, FR-30).

`CodexImages` calls the host bridge, which runs the Codex command line tool. The tests go
through a real bridge on a free port with the fake `codex` program of the bridge's own
tests, which saves a picture the way the real tool does. No test starts a real tool.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from packages.adapters.factory import Adapters
from packages.adapters.image import CodexImages, ImageRequest, png_size
from packages.adapters.tests.test_llm_cli_bridge import serve
from packages.core.enums import Provider
from packages.core.queue import NeedsOwnerError, PlanLimitError, RetryableError
from packages.core.settings import Settings
from tools.cli_bridge.config import BridgeConfig
from tools.cli_bridge.server import make_server
from tools.cli_bridge.service import Bridge
from tools.cli_bridge.tests.support import MISSING, NOW, calls, fake

ROOT = Path(__file__).resolve().parents[3]
PICTURE = ROOT / "samples" / "lighthouse_keeper" / "assets" / "a_storm_sea.png"
ASK = ImageRequest(asset_id="a_harbour", prompt="A small harbour at first light.")


def bridge_with(tmp_path: Path, **tool: object) -> Bridge:
    home = tmp_path / "codex-home"
    command = fake("codex", record=tmp_path / "record.jsonl", image_home=home, **tool)  # type: ignore[arg-type]
    environ = {**os.environ, "CODEX_HOME": str(home)}
    return Bridge(
        BridgeConfig(claude_command=MISSING, codex_command=command),
        environ=environ,
        clock=lambda: NOW,
    )


def adapter(url: str) -> CodexImages:
    return CodexImages(mode="subscription", bridge_url=url, timeout_s=30, queue_s=5, grace_s=5)


def test_fr30_a_picture_comes_back_through_the_bridge_as_a_plan_picture(tmp_path: Path) -> None:
    studio = bridge_with(tmp_path, output="codex_image.jsonl", image=PICTURE)

    with serve(make_server(studio, port=0)) as url:
        result = adapter(url).create(ASK)

    assert result.data == PICTURE.read_bytes()
    assert (result.width, result.height) == png_size(PICTURE.read_bytes())
    assert (result.provider, result.model, result.cost_usd) == (
        Provider.CHATGPT_PLAN,
        "codex image tool",
        Decimal("0"),
    )
    assert result.licence == "Generated on the owner's ChatGPT plan (OpenAI terms of use)"
    (run,) = calls(tmp_path / "record.jsonl")
    assert run["stdin"].endswith("A small harbour at first light.")


def test_fr29_a_usage_limit_makes_the_job_wait_until_the_reset_time(tmp_path: Path) -> None:
    studio = bridge_with(tmp_path, output="codex_limit_today.jsonl", exit_code=1)

    with serve(make_server(studio, port=0)) as url, pytest.raises(PlanLimitError) as limited:
        adapter(url).create(ASK)

    assert limited.value.retry_at is not None
    assert "usage limit" in str(limited.value)


def test_a_tool_that_makes_no_picture_is_tried_again_later(tmp_path: Path) -> None:
    studio = bridge_with(tmp_path, output="codex_image_refused.jsonl")

    with serve(make_server(studio, port=0)) as url, pytest.raises(RetryableError) as failed:
        adapter(url).create(ASK)

    assert "without creating a picture" in str(failed.value)


def test_a_tool_that_is_not_signed_in_with_a_plan_is_an_owner_task(tmp_path: Path) -> None:
    studio = bridge_with(tmp_path, output="codex_image.jsonl", image=PICTURE, sign_in="api")

    with serve(make_server(studio, port=0)) as url, pytest.raises(NeedsOwnerError) as refused:
        adapter(url).create(ASK)

    assert "codex login" in str(refused.value)
    assert calls(tmp_path / "record.jsonl") == []


def test_a_bridge_that_does_not_answer_says_how_to_start_it() -> None:
    with pytest.raises(NeedsOwnerError, match="make bridge-start"):
        CodexImages(
            mode="subscription", bridge_url="http://127.0.0.1:9", timeout_s=5, queue_s=0, grace_s=5
        ).create(ASK)


@pytest.mark.parametrize("mode", ["demo", "api"])
def test_fr28_the_adapter_cannot_be_built_outside_subscription_mode(mode: str) -> None:
    with pytest.raises(NeedsOwnerError, match="subscription mode only"):
        CodexImages(mode=mode, bridge_url="http://127.0.0.1:8189")


def test_subscription_mode_gets_codex_for_its_pictures() -> None:
    settings = Settings(
        database_url="postgresql://unused",
        provider_mode="subscription",
        cli_bridge_url="http://host.docker.internal:8189",
        codex_cli_model="gpt-5.5",
    )

    made = Adapters(settings).image()

    assert isinstance(made, CodexImages)
    assert (made.bridge_url, made.model) == ("http://host.docker.internal:8189", "gpt-5.5")
