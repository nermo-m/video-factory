# ADR 3: GPU outside Docker

## Status

Accepted, 2026-11-11. Design document decision D3 and section 8.

## Context

Clips are generated with Wan 2.2 in ComfyUI on the owner's RTX 3090. ComfyUI, its custom
nodes and many gigabytes of model files are already installed on Windows and are tuned by
hand. GPU passthrough into Docker on Windows goes through WSL2, adds a second place where
drivers and model files must line up, and would make the stack unusable for a reviewer
without an NVIDIA card.

## Decision

ComfyUI runs on the Windows host, outside Docker. Containers reach it over HTTP at
`http://host.docker.internal:8188`. A `gpu` job in the worker does not use the GPU inside
the container: it calls ComfyUI and waits. The host bridge for the Claude Code and Codex
command line tools follows the same pattern on port 8189, because those tools are signed
in on Windows, not in a container.

## Consequences

- No GPU passthrough, no NVIDIA runtime and no model files in any image. The images stay
  small and build on any machine, including CI.
- The owner keeps using and updating ComfyUI the way he already does.
- ComfyUI can be offline. `/health` reports it, the interface shows a banner, and
  everything that does not need the GPU stays usable. In demo mode it is not contacted.
- The one-gpu-job rule lives in the job queue, not in Docker.
- The HTTP details of ComfyUI vary by version, so they are confirmed against the installed
  version before the clip adapter is written.
- `api` and `worker` map `host.docker.internal` explicitly, which also works on Linux.

## Alternatives considered

- **ComfyUI in a container with GPU passthrough.** Reproducible on paper, fragile on
  Windows in practice, and it would move the owner's working installation.
- **Calling the model from Python inside the worker.** Ties the worker image to CUDA and to
  one model's code, and gives up the workflow the owner validates by hand in ComfyUI.
- **A hosted video API.** Costs money per clip and sends the owner's material to a third
  party. The local card is already paid for.
