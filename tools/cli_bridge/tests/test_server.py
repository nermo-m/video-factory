"""The bridge over HTTP: routes, the answers for errors, and who may call it.

The bridge listens on 127.0.0.1 only (section 3.4, NFR-02). A browser on the same PC can
still reach that address, so requests that come from a web page are refused: a page must
not be able to spend the owner's plan.
"""

from __future__ import annotations

import dataclasses
import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tools.cli_bridge.config import BridgeConfig
from tools.cli_bridge.server import make_server
from tools.cli_bridge.service import Bridge
from tools.cli_bridge.tests.support import MISSING, NOW, calls, fake


@dataclasses.dataclass
class Running:
    port: int
    record: Path

    def send(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        headers: dict[str, str] | None = None,
        host: str | None = None,
        raw: bytes | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        payload = (
            raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        )
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", host or f"127.0.0.1:{self.port}")
        sent = {"Content-Type": "application/json"} if method == "POST" else {}
        sent.update(headers or {})
        if method == "POST" and "Content-Length" not in sent:
            sent["Content-Length"] = str(len(payload))
        for name, value in sent.items():
            if value:
                connection.putheader(name, value)
        connection.endheaders(payload)
        response = connection.getresponse()
        text = response.read().decode("utf-8")
        answer_headers = {name.lower(): value for name, value in response.getheaders()}
        connection.close()
        return response.status, answer_headers, json.loads(text) if text else None


def start(config: BridgeConfig, record: Path) -> Iterator[Running]:
    server = make_server(Bridge(config, clock=lambda: NOW), port=0)
    # The short interval is how often the server looks whether it was told to stop.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield Running(port=server.server_address[1], record=record)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


@pytest.fixture
def running(tmp_path: Path) -> Iterator[Running]:
    record = tmp_path / "record.jsonl"
    config = BridgeConfig(
        claude_command=fake("claude", output="claude_text.json", record=record),
        codex_command=fake("codex", output="codex_text.jsonl", record=record),
    )
    yield from start(config, record)


@pytest.fixture
def limited(tmp_path: Path) -> Iterator[Running]:
    record = tmp_path / "record.jsonl"
    config = BridgeConfig(
        claude_command=fake("claude", output="claude_limit_session.json", exit_code=1),
        codex_command=MISSING,
    )
    yield from start(config, record)


def test_health_reports_both_tools(running: Running) -> None:
    status, _, body = running.send("GET", "/health")

    assert status == 200
    assert body["service"] == "cli-bridge"
    assert body["contract"] == "bridge/1"
    assert isinstance(body["pid"], int)
    assert body["tools"]["claude"] == {
        "installed": True,
        "version": "2.1.300",
        "signed_in": True,
        "billing": "plan",
        "plan": "max",
        "ready": True,
        "busy": False,
        "message": "",
    }
    assert body["tools"]["codex"] == {
        "installed": True,
        "version": "0.144.1",
        "signed_in": True,
        "billing": "plan",
        "plan": None,
        "ready": True,
        "busy": False,
        "message": "",
    }


def test_health_never_passes_on_who_is_signed_in(running: Running) -> None:
    _, _, body = running.send("GET", "/health")

    text = json.dumps(body)
    assert "someone@example.com" not in text
    assert "Organisation" not in text
    assert "00000000-0000-4000-8000-00000000abcd" not in text


def test_health_does_not_start_a_model_call(running: Running) -> None:
    running.send("GET", "/health")

    assert calls(running.record) == []
    assert len(calls(running.record, "status")) == 2


def test_health_says_what_to_do_about_a_missing_tool(limited: Running) -> None:
    _, _, body = limited.send("GET", "/health")

    codex = body["tools"]["codex"]
    assert (codex["installed"], codex["signed_in"], codex["ready"]) == (False, False, False)
    assert codex["version"] is None
    assert "CODEX_BIN" in codex["message"]


def test_a_claude_call_over_http(running: Running) -> None:
    status, headers, body = running.send("POST", "/claude", {"prompt": "An idea."})

    assert status == 200
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert body["text"] == "A lighthouse keeper counts the ships he brought home."
    (call,) = calls(running.record)
    assert call["stdin"] == "An idea."


def test_a_codex_call_over_http(running: Running) -> None:
    status, _, body = running.send("POST", "/codex", {"prompt": "Review this."})

    assert status == 200
    assert body["text"] == "The hook is strong, the ending is flat."


def test_text_outside_ascii_survives_the_round_trip(running: Running) -> None:
    running.send("POST", "/claude", {"prompt": "Идея — маяк \U0001f30a"})

    (call,) = calls(running.record)
    assert call["stdin"] == "Идея — маяк \U0001f30a"


def test_fr29_a_plan_limit_answers_with_its_error_class_and_reset_time(limited: Running) -> None:
    status, _, body = limited.send("POST", "/claude", {"prompt": "An idea."})

    assert status == 429
    assert body["error"]["code"] == "plan_limit"
    assert body["error"]["tool"] == "claude"
    assert body["error"]["retry_at"] == "2026-11-12T15:00:00+02:00"
    assert "session limit" in body["error"]["message"]


def test_a_missing_tool_answers_with_its_error_class(limited: Running) -> None:
    status, _, body = limited.send("POST", "/codex", {"prompt": "Review this."})

    assert status == 503
    assert body["error"]["code"] == "not_installed"
    assert body["error"]["retry_at"] is None


def test_a_malformed_request_is_refused_before_a_tool_starts(running: Running) -> None:
    status, _, body = running.send("POST", "/claude", {"prompt": "x", "model": "--bare"})

    assert status == 400
    assert body["error"]["code"] == "bad_request"
    assert calls(running.record) == []
    assert calls(running.record, "status") == []


def test_a_body_that_is_not_json_is_refused(running: Running) -> None:
    status, _, body = running.send("POST", "/claude", raw=b"{not json")

    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_a_body_that_is_too_large_is_refused_unread(running: Running) -> None:
    status, _, body = running.send(
        "POST", "/claude", raw=b"{}", headers={"Content-Length": str(50 * 1024 * 1024)}
    )

    assert status == 413
    assert body["error"]["code"] == "payload_too_large"


def test_a_body_without_a_length_is_refused(running: Running) -> None:
    status, _, body = running.send("POST", "/claude", raw=b"", headers={"Content-Length": ""})

    assert status == 411
    assert body["error"]["code"] == "bad_request"


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", ""])
def test_only_json_is_accepted(running: Running, content_type: str) -> None:
    # A web page can send these three types to another origin without asking first.
    status, _, body = running.send(
        "POST", "/claude", {"prompt": "An idea."}, headers={"Content-Type": content_type}
    )

    assert status == 415
    assert body["error"]["code"] == "unsupported_media_type"
    assert calls(running.record) == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "http://127.0.0.1:3000"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
@pytest.mark.parametrize(("method", "path"), [("POST", "/claude"), ("GET", "/health")])
def test_a_request_from_a_web_page_is_refused(
    running: Running, headers: dict[str, str], method: str, path: str
) -> None:
    body = {"prompt": "An idea."} if method == "POST" else None

    status, _, answer = running.send(method, path, body, headers=headers)

    assert status == 403
    assert answer["error"]["code"] == "forbidden"
    assert calls(running.record) == []
    assert calls(running.record, "status") == []


def test_opening_the_health_address_in_a_browser_works(running: Running) -> None:
    status, _, _ = running.send("GET", "/health", headers={"Sec-Fetch-Site": "none"})

    assert status == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8189", "127.0.0.1.evil.example"])
def test_a_request_addressed_to_another_name_is_refused(running: Running, host: str) -> None:
    # A page can make its own name resolve to 127.0.0.1. The Host header gives it away.
    status, _, answer = running.send("GET", "/health", host=host)

    assert status == 403
    assert answer["error"]["code"] == "forbidden"


def test_the_names_the_worker_and_the_owner_use_are_accepted(running: Running) -> None:
    for name in ("127.0.0.1", "localhost", "host.docker.internal"):
        # Not found is an answer about the address, so the name was accepted.
        status, _, _ = running.send("GET", "/nothing", host=f"{name}:{running.port}")
        assert status == 404, name
        status, _, _ = running.send("GET", "/nothing", host=f"{name.upper()}:{running.port}")
        assert status == 404, name


def test_no_answer_invites_another_origin(running: Running) -> None:
    for method, path, body in (
        ("GET", "/health", None),
        ("POST", "/claude", {"prompt": "An idea."}),
        ("OPTIONS", "/claude", None),
    ):
        _, headers, _ = running.send(method, path, body)
        assert not [name for name in headers if name.startswith("access-control-")]


def test_an_unknown_address_is_not_found(running: Running) -> None:
    status, _, body = running.send("GET", "/nothing")

    assert status == 404
    assert body["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("POST", "/health", "GET"),
        ("GET", "/claude", "POST"),
        ("GET", "/codex", "POST"),
        ("PUT", "/claude", "POST"),
        ("DELETE", "/health", "GET"),
        ("OPTIONS", "/claude", "POST"),
    ],
)
def test_the_wrong_method_is_refused(
    running: Running, method: str, path: str, allowed: str
) -> None:
    status, headers, body = running.send(method, path)

    assert status == 405
    assert headers["allow"] == allowed
    assert body["error"]["code"] == "method_not_allowed"


def test_an_address_with_a_query_is_read_without_it(running: Running) -> None:
    status, _, _ = running.send("GET", "/health?verbose=1")

    assert status == 200


def test_nfr02_the_bridge_listens_on_this_pc_only() -> None:
    server = make_server(
        Bridge(BridgeConfig(claude_command=MISSING, codex_command=MISSING)), port=0
    )
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_nfr02_no_setting_can_make_the_bridge_listen_elsewhere() -> None:
    names = {field.name for field in dataclasses.fields(BridgeConfig)}

    assert not names & {"host", "bind", "address", "listen"}


def test_a_second_bridge_cannot_listen_on_the_same_port(running: Running) -> None:
    second = Bridge(BridgeConfig(claude_command=MISSING, codex_command=MISSING))

    with pytest.raises(OSError):  # noqa: PT011 - the port is taken, whatever the system calls it
        make_server(second, port=running.port)
