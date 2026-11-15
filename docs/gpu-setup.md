# Clips on the graphics card: ComfyUI and Wan 2.2

The studio makes a moving clip from a still picture with Wan 2.2, an open model, through
ComfyUI. ComfyUI runs on Windows next to the studio, not in a container (design decision
D3). The worker reaches it at `COMFYUI_URL`, by default
`http://host.docker.internal:8188`. Nothing else in the studio uses the graphics card:
the plan, the pictures, the voice and the render work without it.

**State on 2026-11-15:** the studio makes its clips itself (board card VFS-29). After
the pictures of a video are made, the worker sends each picture that is to move to
ComfyUI, one at a time, and stores the clip with the picture. The render plays it.

## What is needed

- An NVIDIA card with 24 GB of memory. The measurements here are from an RTX 3090.
- A current NVIDIA driver. ComfyUI asks for PyTorch built for CUDA 13.0 on 20 series cards
  and newer.
- About 45 GB of disk space: 36 GB of model files, the rest is PyTorch.
- `git` and `uv`.

## Install

The versions are the ones this was tried with: ComfyUI 0.45.0, Python 3.13,
PyTorch 2.14.1 for CUDA 13.0.

```powershell
git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git E:\ComfyUI
cd E:\ComfyUI
uv venv --python 3.13 .venv
uv pip install --python .venv\Scripts\python.exe torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu130
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe -c "import torch; print(torch.cuda.get_device_name(0))"
```

The last line must print the name of the card.

## Model files

All six come from `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` on Hugging Face, folder
`split_files`. They are the image-to-video 14B model in fp8 with the 4-step Lightning
LoRA (design decision D6). Wan 2.2 is published under the Apache 2.0 licence.

| File | Goes into `models\` | Size |
|---|---|---|
| `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` | `diffusion_models` | 14.3 GB |
| `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` | `diffusion_models` | 14.3 GB |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `text_encoders` | 6.7 GB |
| `wan_2.1_vae.safetensors` | `vae` | 0.25 GB |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` | `loras` | 1.2 GB |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` | `loras` | 1.2 GB |

The 14B model uses the Wan 2.1 VAE. The `wan2.2_vae` file in the same place belongs to
the 5B model and is not needed.

## Start and stop

Tell the start script where ComfyUI is, once:

```powershell
setx COMFYUI_DIR E:\ComfyUI
```

Open a new PowerShell window after that. From then on `.\tools\start-studio.ps1` starts
ComfyUI with the studio and `.\tools\start-studio.ps1 -Stop` stops the ComfyUI it
started. Its log is `.run\comfyui.log`. To start it by hand:

```powershell
cd E:\ComfyUI
.venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188
```

It listens on this PC only. When it answers, the GPU dot in the studio's status strip
turns green and the banner on the Board goes. ComfyUI's own interface is at
http://127.0.0.1:8188.

## What was measured

One clip, made through ComfyUI's HTTP API on 2026-11-13 from a generated picture of an
episode: 480 by 832, 81 frames at 16 frames a second (5 seconds), 2 steps on the
high-noise model and 2 on the low-noise model with the Lightning LoRAs, cfg 1, sampler
euler, scheduler simple, shift 5. These are the settings of ComfyUI's own template
`video_wan2_2_14B_i2v`.

- The first clip took 374 seconds, including reading 36 GB of model files from disk.
- The picture's subject moved the way the prompt asked and stayed recognisable.
- On 2026-11-15, through the studio's own adapter: 382 seconds for the first clip, then
  352 and 284 seconds for the next two, each 81 frames at 480 by 832. The four sampling
  steps take about 80 seconds of that. The rest is the two 14 GB models taking turns in
  the card's memory, read from disk again each time, because both do not fit at once.
- So count on 5 to 6 minutes for each 5 seconds of moving picture (risk R3). A video of
  eleven shots with lines of 5 to 8 seconds takes about an hour and a half of clips.

## How the studio uses it

- A clip is 16 frames a second and at most 81 frames (5 seconds) a piece. A longer scene
  is made in up to three pieces: each starts from the last frame of the one before, and
  FFmpeg joins them in the worker. A scene longer than 15 seconds holds its last frame.
- The words sent with a picture are the scene's motion, its camera move and the look of
  the video.
- The render brings the clip from 16 to 30 frames a second, with the frames in between
  worked out from the motion, and scales it to the full frame.
- ComfyUI does not answer while the two models take turns in the card's memory: more
  than three minutes of silence was seen. The worker waits up to fifteen minutes of
  silence before it reports ComfyUI as stopped.
- After the last clip that waits, the worker asks ComfyUI to give the card's memory back.
- ComfyUI keeps its own copy of every clip in `E:\ComfyUI\output\video` and of every
  start picture in `E:\ComfyUI\input`. The studio never deletes there. Empty those
  folders by hand when they grow.

The HTTP calls that worked on ComfyUI 0.45.0, for the client of VFS-29 (design section 8
asks to confirm them against the installed version):

| Step | Call |
|---|---|
| Health | `GET /system_stats` |
| Upload the start picture | `POST /upload/image`, a form with `image` and `overwrite` |
| Queue | `POST /prompt` with `{"prompt": graph, "client_id": id}`, answers `prompt_id` |
| Wait | `GET /history/{prompt_id}`, empty until it is done, then `status.status_str` |
| Fetch | `GET /view?filename=...&subfolder=...&type=output`, from `outputs` of the save node |
| Release the memory | `POST /free` with `{"unload_models": true, "free_memory": true}` |

The save node is `SaveVideo` (fed by `CreateVideo`), and its result is listed under
`images` with `"animated": [true]`, as an MP4 file.

## When something is wrong

- **GPU offline in the studio.** ComfyUI is not answering on port 8188. Start it, and look
  at `.run\comfyui.log`.
- **ComfyUI stops with a CUDA or driver message.** Update the NVIDIA driver.
- **Out of memory.** Close other programs that use the card. A game or another model
  next to Wan 2.2 does not fit in 24 GB.
