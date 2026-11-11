"""ComfyUI reachability probe, tested against a local stand-in server."""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from packages.adapters.clip.probe import comfyui_reachable


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status = 200 if self.path == "/system_stats" else 404
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: object) -> None:
        """Keep the test output quiet."""


@pytest.fixture
def stand_in() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_reachable_when_system_stats_answers(stand_in: str) -> None:
    assert comfyui_reachable(stand_in) is True
    assert comfyui_reachable(stand_in + "/") is True


def test_not_reachable_when_nothing_listens() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # The socket is closed again, so nothing listens on that port now.

    assert comfyui_reachable(f"http://127.0.0.1:{port}", timeout_s=0.5) is False


def test_not_reachable_when_the_port_does_not_speak_http() -> None:
    def echo_once(server: socket.socket) -> None:
        connection, _ = server.accept()
        with connection:
            connection.sendall(connection.recv(1024))

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        thread = threading.Thread(target=echo_once, args=(server,), daemon=True)
        thread.start()

        reachable = comfyui_reachable(f"http://127.0.0.1:{server.getsockname()[1]}", timeout_s=2)
        thread.join(timeout=5)

    assert reachable is False


def test_not_reachable_when_the_endpoint_is_missing(stand_in: str) -> None:
    assert comfyui_reachable(stand_in + "/somewhere-else") is False


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/x", "not a url", ""])
def test_only_http_urls_are_ever_opened(url: str) -> None:
    assert comfyui_reachable(url) is False
