"""The bridge over HTTP, on 127.0.0.1 only (design doc section 3.4, NFR-02).

A program on this PC, or the worker container through `host.docker.internal`, may call
it. A web page may not: a browser can reach 127.0.0.1 too, and a page must not be able to
spend the owner's plan. Three checks keep pages out:

* the `Host` header must be one of the names the bridge is reached by, which stops a page
  whose own name was made to resolve to 127.0.0.1;
* a request that says it comes from a page (`Origin`, or `Sec-Fetch-Site` other than
  `none`) is refused;
* a body must be `application/json`, which a page cannot send to another origin without
  asking first, and the bridge never answers that question with a yes.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

from tools.cli_bridge.contract import parse_claude_request, parse_codex_request
from tools.cli_bridge.errors import (
    FORBIDDEN,
    INTERNAL,
    METHOD_NOT_ALLOWED,
    NOT_FOUND,
    PAYLOAD_TOO_LARGE,
    UNSUPPORTED_MEDIA_TYPE,
    BridgeError,
    bad_request,
)
from tools.cli_bridge.service import Bridge

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
# The names the bridge is reached by: from this PC, and from the worker container.
NAMES = ("127.0.0.1", "localhost", "host.docker.internal")
MAX_BODY_BYTES = 2 * 1024 * 1024
# How long a caller that announced more than it sent is waited for before it is answered.
DRAIN_SECONDS = 0.5
ROUTES = {"/health": "GET", "/claude": "POST", "/codex": "POST"}


class _Handler(BaseHTTPRequestHandler):
    bridge: ClassVar[Bridge]
    server_version = "cli-bridge"
    sys_version = ""
    # Seconds a client may take to send its request.
    timeout = 30
    # Bytes of the request body that were announced and have not been read.
    _unread = 0

    def _handle(self) -> None:
        route = self.path.split("?", 1)[0]
        announced = (self.headers.get("Content-Length") or "").strip()
        self._unread = int(announced) if announced.isdecimal() else 0
        try:
            status, body, headers = 200, self._answer(route), {}
        except BridgeError as error:
            status, body = error.status, error.to_json()
            headers = {"Allow": ROUTES[route]} if error.code == METHOD_NOT_ALLOWED else {}
        except Exception as error:
            # The frames say where it happened. The message is left out: it could quote
            # something from the request.
            frames = "".join(traceback.format_tb(error.__traceback__))
            log.error("bridge failure", extra={"error": type(error).__name__, "frames": frames})
            failure = BridgeError(INTERNAL, "The bridge failed. See its log.", status=500)
            status, body, headers = 500, failure.to_json(), {}
        self._drain()
        self._send(status, body, headers)
        known = route if route in ROUTES else "other"
        log.info("bridge request", extra={"method": self.command, "route": known, "status": status})

    # http.server looks for one method per HTTP verb. Every verb gets the same checks,
    # so a wrong one is answered like any other refusal.
    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_OPTIONS(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def _answer(self, route: str) -> dict[str, Any]:
        self._refuse_web_pages()
        if route not in ROUTES:
            raise BridgeError(NOT_FOUND, "There is nothing at this address.", status=404)
        if self.command != ROUTES[route]:
            raise BridgeError(METHOD_NOT_ALLOWED, f"Use {ROUTES[route]} for {route}.", status=405)
        if route == "/health":
            return self.bridge.health()
        body = self._body()
        longest = self.bridge.config.max_timeout_seconds
        if route == "/claude":
            return self.bridge.claude(parse_claude_request(body, max_timeout_seconds=longest))
        return self.bridge.codex(parse_codex_request(body, max_timeout_seconds=longest))

    def _refuse_web_pages(self) -> None:
        # The port this request arrived on.
        port = self.connection.getsockname()[1]
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in {f"{name}:{port}" for name in NAMES}:
            raise BridgeError(FORBIDDEN, "This address is not served.", status=403)
        from_page = (
            self.headers.get("Origin") is not None
            or (self.headers.get("Sec-Fetch-Site") or "none").strip().lower() != "none"
        )
        if from_page:
            raise BridgeError(FORBIDDEN, "Requests from web pages are refused.", status=403)

    def _body(self) -> object:
        media_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise BridgeError(
                UNSUPPORTED_MEDIA_TYPE, "Send the request as application/json.", status=415
            )
        declared = self.headers.get("Content-Length")
        if declared is None:
            raise bad_request("The request needs a Content-Length.", status=411)
        if not declared.strip().isdecimal():
            raise bad_request("The Content-Length is not a number.")
        length = int(declared)
        if length > MAX_BODY_BYTES:
            raise BridgeError(
                PAYLOAD_TOO_LARGE,
                f"The request is larger than {MAX_BODY_BYTES} bytes.",
                status=413,
            )
        sent = self.rfile.read(length)
        self._unread = 0
        try:
            return json.loads(sent.decode("utf-8"))
        except ValueError:
            raise bad_request("The request body is not JSON.") from None

    def _drain(self) -> None:
        """Read what is left of a request that is answered without having been read.

        A connection that is closed with unread input can lose the answer on its way out:
        the caller then sees a broken connection instead of the refusal. A caller that
        announced more than it sends is waited for only briefly, and a body beyond the
        size limit is not read to its end.
        """
        remaining = min(self._unread, MAX_BODY_BYTES)
        if remaining == 0:
            return
        self.connection.settimeout(DRAIN_SECONDS)
        with contextlib.suppress(OSError):
            while remaining > 0:
                chunk = self.rfile.read1(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
        self.connection.settimeout(self.timeout)

    def _send(self, status: int, body: dict[str, Any], headers: dict[str, str]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except OSError:
            # The caller went away while the tool was working. Nothing is left to tell it.
            log.info("bridge caller gone", extra={"status": status})

    def log_message(self, format: str, *args: Any) -> None:
        """Requests are logged once, by `_handle`, without anything the caller sent."""


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows this option would let a second program listen on a port that is
    # already taken, so a second bridge would start next to the first. Elsewhere it
    # only lets a restarted bridge have its port back at once.
    allow_reuse_address = sys.platform != "win32"


def make_server(bridge: Bridge, *, port: int) -> ThreadingHTTPServer:
    """An HTTP server for a bridge. Port 0 picks a free port, which tests use."""
    handler: Callable[..., BaseHTTPRequestHandler] = type(
        "Handler", (_Handler,), {"bridge": bridge}
    )
    return _Server((HOST, port), handler)
