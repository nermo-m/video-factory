"""Clips from Wan 2.2 through ComfyUI on the owner's PC (design doc section 8, D3, D6).

ComfyUI runs on the host, outside the containers, and owns the graphics card. This client
speaks its HTTP API: upload the start picture, queue a graph, wait for the history entry,
fetch the clip and its last frame. Every call here was confirmed against ComfyUI 0.45.0
(`docs/gpu-setup.md`).

The graph is ComfyUI's own template `video_wan2_2_14B_i2v`: the image-to-video 14B model
in fp8 with the 4-step Lightning LoRAs, two steps on the high-noise model and two on the
low-noise one. One node is added: the last frame is saved as a picture, so a scene longer
than one piece goes on from it.

Nothing here costs money or counts against a plan. The model is open and runs locally.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import uuid
from typing import Any
from urllib.parse import quote, urlsplit

from packages.adapters.clip.base import CLIP_FPS, ClipRequest, ClipResult
from packages.core.queue import NeedsOwnerError, RetryableError

MODEL = "wan2.2_i2v_14B_fp8 + lightx2v 4 steps"
# One piece took 374 seconds on an RTX 3090 with the model files read from disk first.
TIMEOUT_S = 1800.0
POLL_S = 2.0
CONNECT_S = 10.0
# ComfyUI does not answer while the two 14 GB models take turns in the card's memory: more
# than three minutes of silence was seen on the owner's PC, and the clip was still being
# made. So silence while a clip is being made is waited out for as long as half of what a
# clip may take. Giving up early leaves ComfyUI working on a clip nobody fetches.
PATIENCE_S = 900.0
SETUP = "docs/gpu-setup.md"

NEGATIVE = (
    "static, frozen, blurry details, subtitles, captions, text, watermark, logo, worst "
    "quality, low quality, jpeg artifacts, deformed, extra fingers, extra limbs, "
    "flickering, morphing face"
)

_FILES = {
    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "vae": "wan_2.1_vae.safetensors",
    "high": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    "low": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    "high_lora": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    "low_lora": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
}


def graph(request: ClipRequest, *, picture: str, prefix: str) -> dict[str, Any]:
    """The ComfyUI graph for one piece. `picture` is the uploaded start picture's name."""

    def lora(model: str, name: str) -> dict[str, Any]:
        return {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": [model, 0], "lora_name": name, "strength_model": 1.0},
        }

    def shift(model: str) -> dict[str, Any]:
        return {"class_type": "ModelSamplingSD3", "inputs": {"model": [model, 0], "shift": 5.0}}

    def sampler(model: str, latent: list[Any], *, first: bool) -> dict[str, Any]:
        return {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": [model, 0],
                "positive": ["wan", 0],
                "negative": ["wan", 1],
                "latent_image": latent,
                "add_noise": "enable" if first else "disable",
                "noise_seed": request.seed if first else 0,
                "steps": 4,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "start_at_step": 0 if first else 2,
                "end_at_step": 2 if first else 10000,
                "return_with_leftover_noise": "enable" if first else "disable",
            },
        }

    def text(words: str) -> dict[str, Any]:
        return {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": words}}

    return {
        "clip": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": _FILES["clip"], "type": "wan", "device": "default"},
        },
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": _FILES["vae"]}},
        "high": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": _FILES["high"], "weight_dtype": "default"},
        },
        "low": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": _FILES["low"], "weight_dtype": "default"},
        },
        "high_lora": lora("high", _FILES["high_lora"]),
        "low_lora": lora("low", _FILES["low_lora"]),
        "high_shift": shift("high_lora"),
        "low_shift": shift("low_lora"),
        "pos": text(request.prompt),
        "neg": text(NEGATIVE),
        "image": {"class_type": "LoadImage", "inputs": {"image": picture}},
        "wan": {
            "class_type": "WanImageToVideo",
            "inputs": {
                "positive": ["pos", 0],
                "negative": ["neg", 0],
                "vae": ["vae", 0],
                "width": request.width,
                "height": request.height,
                "length": request.frames,
                "batch_size": 1,
                "start_image": ["image", 0],
            },
        },
        "s1": sampler("high_shift", ["wan", 2], first=True),
        "s2": sampler("low_shift", ["s1", 0], first=False),
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["s2", 0], "vae": ["vae", 0]}},
        "video": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["decode", 0], "fps": CLIP_FPS},
        },
        "save": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["video", 0],
                "filename_prefix": f"video/{prefix}",
                "format": "auto",
                "codec": "auto",
            },
        },
        "last": {
            "class_type": "ImageFromBatch",
            "inputs": {"image": ["decode", 0], "batch_index": request.frames - 1, "length": 1},
        },
        "save_last": {
            "class_type": "SaveImage",
            "inputs": {"images": ["last", 0], "filename_prefix": f"video/{prefix}_last"},
        },
    }


class ComfyClips:
    """ClipAdapter: Wan 2.2 image-to-video through ComfyUI on the host."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = TIMEOUT_S,
        poll_s: float = POLL_S,
        connect_s: float = CONNECT_S,
        patience_s: float = PATIENCE_S,
    ) -> None:
        if urlsplit(base_url).scheme not in {"http", "https"}:
            raise NeedsOwnerError(
                "COMFYUI_URL must be an http address such as "
                f"http://host.docker.internal:8188, not '{base_url}'."
            )
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.connect_s = connect_s
        self.patience_s = patience_s

    # --- the adapter -----------------------------------------------------------------

    def create(self, request: ClipRequest) -> ClipResult:
        started = time.perf_counter()
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", request.name).strip("_")[:40] or "clip"
        prefix = f"vf_{safe}_{uuid.uuid4().hex[:8]}"
        picture = self._upload(f"{prefix}.png", request.picture)
        prompt_id = self._queue(graph(request, picture=picture, prefix=prefix))
        outputs = self._wait(prompt_id, started)
        video = self._fetch(_file_of(outputs, "save"))
        last_frame = self._fetch(_file_of(outputs, "save_last"))
        return ClipResult(
            video=video,
            last_frame=last_frame,
            frames=request.frames,
            fps=CLIP_FPS,
            width=request.width,
            height=request.height,
            model=MODEL,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    def release(self) -> None:
        self._call(
            "/free",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
            headers={"Content-Type": "application/json"},
        )

    # --- the calls -------------------------------------------------------------------

    def _call(
        self, path: str, *, data: bytes | None = None, headers: dict[str, str] | None = None
    ) -> bytes:
        # The scheme was checked when this client was made, so this cannot open a file.
        asked = urllib.request.Request(  # noqa: S310
            self.base_url + path, data=data, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(asked, timeout=self.connect_s) as answer:  # noqa: S310
                return bytes(answer.read())
        except urllib.error.HTTPError as refused:
            raise _RefusedError(refused.code, refused.read()) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise NeedsOwnerError(
                f"ComfyUI does not answer at {self.base_url}, so no clip can be made. Start "
                "it on the PC (`tools/start-studio.ps1` does it), then run the step again. "
                f"See {SETUP}."
            ) from None

    def _upload(self, name: str, picture: bytes) -> str:
        boundary = uuid.uuid4().hex
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
                "Content-Type: image/png\r\n\r\n"
            ).encode()
            + picture
            + (
                f"\r\n--{boundary}\r\n"
                'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
                f"true\r\n--{boundary}--\r\n"
            ).encode()
        )
        try:
            answer = self._call(
                "/upload/image",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
        except _RefusedError as refused:
            raise RetryableError(
                f"ComfyUI did not take the start picture (HTTP {refused.status})."
            ) from None
        stored = _document(answer).get("name")
        if not isinstance(stored, str) or not stored:
            raise self._not_comfyui()
        return stored

    def _queue(self, nodes: dict[str, Any]) -> str:
        body = json.dumps({"prompt": nodes, "client_id": uuid.uuid4().hex}).encode()
        try:
            answer = self._call("/prompt", data=body, headers={"Content-Type": "application/json"})
        except _RefusedError as refused:
            # A graph is refused when a node or a model file is missing: nothing a retry
            # changes, and the owner's to install.
            raise NeedsOwnerError(
                f"ComfyUI refused the clip: {_why_refused(refused.body)} Check that the six "
                f"Wan 2.2 model files are in place ({SETUP})."
            ) from None
        prompt_id = _document(answer).get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise self._not_comfyui()
        return prompt_id

    def _wait(self, prompt_id: str, started: float) -> dict[str, Any]:
        silent_since: float | None = None
        while True:
            try:
                history = _document(self._call(f"/history/{quote(prompt_id)}"))
                silent_since = None
            except _RefusedError as refused:
                raise RetryableError(
                    f"ComfyUI could not say how the clip is doing (HTTP {refused.status})."
                ) from None
            except NeedsOwnerError:
                # It took the clip a moment ago, so it is busy, not gone. Only a long
                # silence means it has stopped.
                now = time.perf_counter()
                silent_since = now if silent_since is None else silent_since
                if now - silent_since > self.patience_s:
                    raise NeedsOwnerError(
                        f"ComfyUI took the clip and then stopped answering at {self.base_url} "
                        f"for more than {self.patience_s:g} seconds. Look at its log "
                        f"(.run/comfyui.log), start it again, then run the step again."
                    ) from None
                time.sleep(self.poll_s)
                continue
            entry = history.get(prompt_id)
            if isinstance(entry, dict):
                status = entry.get("status")
                status = status if isinstance(status, dict) else {}
                if status.get("status_str") != "success":
                    raise RetryableError(
                        f"The clip failed on the graphics card: {_why_failed(status)}"
                    )
                outputs = entry.get("outputs")
                if not isinstance(outputs, dict):
                    raise self._not_comfyui()
                return outputs
            if time.perf_counter() - started > self.timeout_s:
                raise RetryableError(
                    f"The clip did not finish within {self.timeout_s:g} seconds. ComfyUI may "
                    "be busy with something else, or the graphics card is out of memory."
                )
            time.sleep(self.poll_s)

    def _fetch(self, file: dict[str, Any]) -> bytes:
        address = (
            f"/view?filename={quote(str(file['filename']))}"
            f"&subfolder={quote(str(file.get('subfolder', '')))}"
            f"&type={quote(str(file.get('type', 'output')))}"
        )
        try:
            data = self._call(address)
        except _RefusedError as refused:
            raise RetryableError(
                f"ComfyUI made the clip and did not hand it over (HTTP {refused.status})."
            ) from None
        if not data:
            raise RetryableError("ComfyUI handed over an empty file for the clip.")
        return data

    def _not_comfyui(self) -> NeedsOwnerError:
        return NeedsOwnerError(
            f"What answers at {self.base_url} is not ComfyUI as this app knows it "
            f"(0.45.0). Check COMFYUI_URL. See {SETUP}."
        )


class _RefusedError(Exception):
    """ComfyUI answered with an HTTP error."""

    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(status)
        self.status = status
        self.body = body


def _document(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _file_of(outputs: dict[str, Any], node: str) -> dict[str, Any]:
    """The first file a save node wrote."""
    saved = outputs.get(node)
    for files in saved.values() if isinstance(saved, dict) else []:
        first = files[0] if isinstance(files, list) and files else None
        if isinstance(first, dict) and isinstance(first.get("filename"), str):
            return dict(first)
    raise RetryableError(f"ComfyUI finished the clip and its '{node}' node wrote no file.")


def _why_refused(body: bytes) -> str:
    """What ComfyUI said about a refused graph, in one line."""
    refusal = _document(body)
    said = []
    error = refusal.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        said.append(error["message"])
    nodes = refusal.get("node_errors")
    for node in nodes.values() if isinstance(nodes, dict) else []:
        for problem in node.get("errors", []) if isinstance(node, dict) else []:
            if isinstance(problem, dict):
                said.append(f"{problem.get('message', '')} ({problem.get('details', '')})")
    return ("; ".join(part for part in said if part) or "it gave no reason")[:600] + "."


def _why_failed(status: dict[str, Any]) -> str:
    """What went wrong while a clip was made, from the history's messages."""
    for message in status.get("messages") or []:
        if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
            details = message[1] if isinstance(message[1], dict) else {}
            words = str(details.get("exception_message") or "").strip()
            node = str(details.get("node_type") or "").strip()
            if words:
                return f"{words[:400]}" + (f" (in {node})" if node else "")
    return "ComfyUI gave no reason. Its log is .run/comfyui.log."
