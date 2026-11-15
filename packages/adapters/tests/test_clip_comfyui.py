"""The clip adapter: Wan 2.2 through ComfyUI's HTTP API (design doc section 8, FR-07).

A small server stands in for ComfyUI and answers the six calls the adapter makes, in the
shapes ComfyUI 0.45.0 answered on the owner's PC (`docs/gpu-setup.md`).
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from packages.adapters.clip import ClipRequest, ComfyClips, comfyui, wan_frames
from packages.core.queue import NeedsOwnerError, RetryableError

PICTURE = b"\x89PNG\r\n\x1a\n" + b"start picture"
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"moving"
LAST = b"\x89PNG\r\n\x1a\n" + b"last frame"


class Comfy:
    """What the stand-in ComfyUI was asked, and how it is told to answer."""

    def __init__(self) -> None:
        self.uploads: list[bytes] = []
        self.graphs: list[dict[str, Any]] = []
        self.freed: list[dict[str, Any]] = []
        self.polls = 0
        # How many times the history is empty before the clip is there.
        self.busy_polls = 1
        self.refuse: dict[str, Any] | None = None
        self.outcome = "success"
        self.messages: list[Any] = []
        # How many of the first questions about the clip get no answer in time. ComfyUI
        # does not answer while it reads a model file into memory.
        self.silent_polls = 0
        self.silent_s = 0.0


@contextlib.contextmanager
def serving(comfy: Comfy) -> Iterator[str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, document: Any) -> None:
            self._send(status, json.dumps(document).encode())

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/upload/image":
                comfy.uploads.append(body)
                self._json(200, {"name": f"upload_{len(comfy.uploads)}.png", "subfolder": ""})
            elif self.path == "/prompt":
                if comfy.refuse is not None:
                    self._json(400, comfy.refuse)
                    return
                comfy.graphs.append(json.loads(body)["prompt"])
                self._json(200, {"prompt_id": f"p{len(comfy.graphs)}", "number": 1})
            elif self.path == "/free":
                comfy.freed.append(json.loads(body))
                self._send(200, b"")
            else:
                self._send(404, b"{}")

        def do_GET(self) -> None:
            address = urlsplit(self.path)
            if address.path.startswith("/history/"):
                prompt_id = address.path.rsplit("/", 1)[1]
                comfy.polls += 1
                if comfy.polls <= comfy.silent_polls:
                    time.sleep(comfy.silent_s)
                if comfy.polls <= comfy.busy_polls:
                    self._json(200, {})
                    return
                self._json(
                    200,
                    {
                        prompt_id: {
                            "status": {
                                "status_str": comfy.outcome,
                                "completed": comfy.outcome == "success",
                                "messages": comfy.messages,
                            },
                            "outputs": {
                                "save": {
                                    "images": [
                                        {
                                            "filename": "vf_00001_.mp4",
                                            "subfolder": "video",
                                            "type": "output",
                                        }
                                    ],
                                    "animated": [True],
                                },
                                "save_last": {
                                    "images": [
                                        {
                                            "filename": "vf_last_00001_.png",
                                            "subfolder": "video",
                                            "type": "output",
                                        }
                                    ]
                                },
                            },
                        }
                    },
                )
            elif address.path == "/view":
                name = parse_qs(address.query)["filename"][0]
                if name.endswith(".mp4"):
                    self._send(200, VIDEO, "video/mp4")
                else:
                    self._send(200, LAST, "image/png")
            else:
                self._send(404, b"{}")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(**fields: Any) -> ClipRequest:
    given: dict[str, Any] = {
        "name": "s01 picture",
        "picture": PICTURE,
        "prompt": "The keeper climbs. Slow push in.",
        "frames": 81,
        "seed": 7,
    }
    return ClipRequest(**{**given, **fields})


def clips(url: str, **options: Any) -> ComfyClips:
    return ComfyClips(url, poll_s=0.01, **options)


def test_fr07_a_picture_becomes_a_clip_and_its_last_frame() -> None:
    comfy = Comfy()
    with serving(comfy) as url:
        made = clips(url).create(request())

    assert (made.video, made.last_frame) == (VIDEO, LAST)
    assert (made.frames, made.fps, made.width, made.height) == (81, 16.0, 480, 832)
    assert made.model == "wan2.2_i2v_14B_fp8 + lightx2v 4 steps"
    # The picture was sent as it is, and the clip was waited for.
    assert PICTURE in comfy.uploads[0]
    assert comfy.polls == 2


def test_the_graph_is_the_one_that_worked_on_the_owners_card() -> None:
    comfy = Comfy()
    with serving(comfy) as url:
        clips(url).create(request(frames=49, seed=99, width=720, height=1280))

    graph = comfy.graphs[0]
    assert graph["image"]["inputs"]["image"] == "upload_1.png"
    assert graph["pos"]["inputs"]["text"] == "The keeper climbs. Slow push in."
    assert "low quality" in graph["neg"]["inputs"]["text"]
    assert graph["wan"]["inputs"] == {
        "positive": ["pos", 0],
        "negative": ["neg", 0],
        "vae": ["vae", 0],
        "width": 720,
        "height": 1280,
        "length": 49,
        "batch_size": 1,
        "start_image": ["image", 0],
    }
    # Two steps on the high-noise model, then two on the low-noise one (D6).
    first, second = graph["s1"]["inputs"], graph["s2"]["inputs"]
    assert (first["noise_seed"], first["steps"], first["cfg"]) == (99, 4, 1.0)
    assert (first["start_at_step"], first["end_at_step"]) == (0, 2)
    assert (second["start_at_step"], second["add_noise"]) == (2, "disable")
    assert graph["video"]["inputs"]["fps"] == 16.0
    # The last frame is saved too: a longer scene goes on from it.
    assert graph["last"]["inputs"] == {"image": ["decode", 0], "batch_index": 48, "length": 1}
    assert graph["save_last"]["class_type"] == "SaveImage"


def test_the_card_is_given_back_when_asked() -> None:
    comfy = Comfy()
    with serving(comfy) as url:
        clips(url).release()

    assert comfy.freed == [{"unload_models": True, "free_memory": True}]


def test_comfyui_that_does_not_answer_is_the_owners_to_start() -> None:
    with pytest.raises(NeedsOwnerError, match="ComfyUI does not answer"):
        clips("http://127.0.0.1:9", connect_s=0.5).create(request())


def test_a_graph_comfyui_refuses_names_what_is_missing() -> None:
    comfy = Comfy()
    comfy.refuse = {
        "error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed"},
        "node_errors": {
            "high": {
                "errors": [
                    {
                        "message": "Value not in list",
                        "details": "unet_name: 'wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors'",
                    }
                ]
            }
        },
    }
    with serving(comfy) as url, pytest.raises(NeedsOwnerError) as refused:
        clips(url).create(request())

    assert "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors" in str(refused.value)
    assert "docs/gpu-setup.md" in str(refused.value)


def test_a_clip_that_fails_on_the_card_is_tried_again_and_says_why() -> None:
    comfy = Comfy()
    comfy.outcome = "error"
    comfy.messages = [
        ["execution_start", {}],
        ["execution_error", {"exception_message": "CUDA out of memory", "node_type": "KSampler"}],
    ]
    with serving(comfy) as url, pytest.raises(RetryableError, match="CUDA out of memory"):
        clips(url).create(request())


def test_a_clip_that_takes_too_long_is_given_up() -> None:
    comfy = Comfy()
    comfy.busy_polls = 10_000
    with serving(comfy) as url, pytest.raises(RetryableError, match="did not finish"):
        clips(url, timeout_s=0.05).create(request())


def test_an_address_that_is_not_http_is_refused() -> None:
    with pytest.raises(NeedsOwnerError, match="COMFYUI_URL"):
        ComfyClips("file:///etc/passwd")


@pytest.mark.parametrize(
    ("seconds", "frames"),
    [(0.5, 17), (1.0, 17), (2.0, 33), (3.1, 53), (5.0, 81), (5.1, 81), (60.0, 81)],
)
def test_a_clip_has_four_times_n_plus_one_frames_and_at_most_five_seconds(
    seconds: float, frames: int
) -> None:
    assert wan_frames(seconds) == frames


def test_comfyui_that_is_silent_while_it_loads_a_model_is_waited_for() -> None:
    # Seen on the owner's PC: no answer for more than ten seconds while 14 GB are read.
    comfy = Comfy()
    comfy.silent_polls, comfy.silent_s, comfy.busy_polls = 2, 0.4, 3
    with serving(comfy) as url:
        made = clips(url, connect_s=0.1, patience_s=30).create(request())

    assert made.video == VIDEO


def test_comfyui_that_stays_silent_is_the_owners_to_look_at() -> None:
    comfy = Comfy()
    comfy.silent_polls, comfy.silent_s = 10_000, 0.3
    with serving(comfy) as url, pytest.raises(NeedsOwnerError, match="stopped answering"):
        clips(url, connect_s=0.1, patience_s=0.5).create(request())


def test_the_patience_with_a_silent_comfyui_is_as_long_as_a_clip_may_take() -> None:
    # Seen on the owner's PC on 2026-11-15: no answer for more than three minutes while
    # the two models took turns in the card's memory, and the clip was still being made.
    assert comfyui.PATIENCE_S >= comfyui.TIMEOUT_S / 2 >= 900
