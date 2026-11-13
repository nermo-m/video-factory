# Video Factory Studio

A self-hosted studio that turns one idea into a finished short vertical video.

A planning model writes a complete, machine-readable Episode Spec. Generation tools produce
images, short clips and narration. A deterministic render engine assembles the video from
the spec. The owner approves the plan and the assets, reviews the result, and uploads the
accepted video by hand. The app never posts anything itself.

> **Status: early development (milestone M3, assets).** An idea becomes a video in the
> browser: New episode on the Board turns an idea into a plan, the episode's workspace
> shows it, lets you edit it or ask for changes in words, and after you approve the plan
> and the pictures the worker speaks, draws and joins the video, which plays in the Render
> tab and can be downloaded. In demo mode that is always the bundled sample story, with
> no keys and no accounts. In subscription mode it is your own idea, planned and
> illustrated on your own Claude and ChatGPT plans. Quality checks, export packs, clips
> and uploads of your own pictures are not built yet. This README grows with each
> milestone and is finished in M8.

## Try it in the browser

Prerequisite: Docker with Compose. No keys, no GPU, no accounts and no model download.

```bash
make up   # then open http://127.0.0.1:3000
```

Choose New episode, type any idea and press Start. When the plan needs you, read it,
change a title if you like, and approve it. Approve the pictures, and a few minutes
later the Render tab plays the video. Leave the narration as it is unless you have run
`make models`: without the voice model, the bundled voice only knows the sample's words,
and the episode page tells you so if you change them.

## Make a video from your own idea

This uses your own plans and no API key: Claude Code writes the plan, Codex makes the
pictures, and the voice is spoken on your PC. Both command line tools must be installed
and signed in with a plan (`claude auth login`, `codex login`).

```bash
make models   # once: download the Kokoro voice (354 MB), so any narration can be spoken
```

On Windows, one command in PowerShell starts everything, also Docker Desktop when it is
not running:

```powershell
.\tools\start-studio.ps1          # your own ideas, on your plans
.\tools\start-studio.ps1 -Stop    # stop it. Episodes and videos are kept
```

Elsewhere, set `PROVIDER_MODE=subscription` in `.env`, then:

```bash
make up       # starts the stack and the bridge to the two tools on this PC
```

Open http://127.0.0.1:3000 and choose New episode. Type your idea and press Start. After
about two minutes the plan needs you: read it, edit a scene or ask for a change in
words, and approve it. The pictures are then made one by one, about 40 seconds each. Look
at them in the Assets tab, make one again if you like, and approve them. A few minutes
later the Render tab plays the video and offers it as a download.

One episode needs about five planning calls on the Claude plan and four pictures on the
ChatGPT plan. The app counts its own use and pauses at your budget, which you set under
Settings, Usage and limits. `make down` stops everything.

## Render the sample episode

Prerequisite: Docker with Compose. No keys, no GPU, no accounts and no model download.

```bash
make demo-render   # writes export/demo/video.mp4 and export/demo/video_contact_sheet.jpg
```

The sample is "The Lighthouse Keeper", an original 45 second story with pictures drawn
in code. Its narration is bundled as recordings. To hear it spoken live by the local
Kokoro voice instead, run `make models` once (354 MB) and render again. Without `make`:
copy `.env.example` to `.env`, then
`docker compose run --rm --no-deps --build --user 0 --volume "$PWD/export:/export" worker python -m apps.worker.demo_render --out /export/demo`.

The command checks the finished file: 1080 by 1920, 30 frames a second, H.264 yuv420p,
AAC 192 kbps, index at the front, length within 2 seconds of 45. The sound is mixed to
-14 LUFS with true peak under -1 dB.

### Render time (RN-11)

Target: a 45 second episode renders in under 6 minutes with 4 CPU workers. Measured on
2026-11-12 inside the worker image, for the 44.2 second sample at full size, from
the resolved spec to the finished file (frames, audio mix, encode, join, contact sheet):

| Workers | Render time |
| --- | --- |
| 4 | 53 seconds |
| 1 | 94 seconds |

Machine: a desktop PC with 16 logical CPU cores and 16 GB of memory given to Docker
Desktop on Windows. Rendering again after an edit encodes only the scenes that changed.

## Design in one paragraph

A deterministic production pipeline with an autonomous critic that reviews and repairs its
own output, and an optional producer that runs an episode end to end inside strict
guardrails. Every external tool sits behind an adapter with a mock twin, so the whole
pipeline runs in demo mode on any machine: no GPU, no API keys, no accounts.

## Repository layout

```text
apps/web/            Next.js interface
apps/api/            FastAPI service
apps/worker/         job loops and job handlers
packages/core/       models, state machine, queue, storage interface
packages/render/     resolver, compositor, primitives, theme, audio, encode
packages/skills/     planner skills with schemas, examples and tests
packages/agents/     agent runtime, critic, producer, evaluators
packages/adapters/   llm, image, clip, tts, storage, each with a mock
schemas/             JSON Schemas for the pipeline documents
samples/             original demo spec, assets, recorded model responses
docs/                architecture, decision records, plans and questions
scripts/             repository checks
tools/               progress tracker server and sync, host bridge to the command line tools
```

## How it is built

[docs/architecture.md](docs/architecture.md) has the component diagram, the pipeline state
machine and the job queue. The reasons behind the main choices are in the
[architecture decision records](docs/adr/README.md).

## Development setup

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 22 or newer with
[pnpm](https://pnpm.io/), and git. uv installs the pinned Python version by itself.

```bash
make setup        # install Python and Node tooling and the git hooks
make check        # lint, types, unit tests and the asset registry check
make test-integration   # integration tests on a real Postgres (needs Docker)
make generate-api # rewrite apps/api/openapi.json and the typed web client
make coverage     # unit and integration tests with the 80 percent coverage gate
make audit        # known vulnerabilities in Python and Node packages
make secret-scan  # gitleaks over every commit
make precommit    # run every pre-commit hook on every file
make progress     # serve the build-status page at http://127.0.0.1:8094
```

Without `make` (for example on plain Windows), run the commands inside the
[Makefile](Makefile) directly: each target is one or two lines.

## Run the stack

Prerequisite: Docker with Compose.

```bash
make up           # create .env if missing, build, start, wait until all four services are healthy
make ps           # web on 127.0.0.1:3000, api on 127.0.0.1:8000, db on 127.0.0.1:5433
curl http://127.0.0.1:8000/api/v1/health   # database, storage, ComfyUI, demo mode
make noop-job     # send one no-op job through the queue and wait for the worker
make demo-render  # render the sample episode into export/demo
make models       # download the Kokoro voice model into the models volume (354 MB, once)
make voice-test   # run the real voice inside the worker image (needs make models)
make render-test  # golden frames, audio and encode tests with FFmpeg in the worker image
make e2e          # browser tests (Playwright and axe) in the pinned Linux image, in a stack and database of their own
make down         # stop (data volumes are kept)
```

With `PROVIDER_MODE=subscription`, `make up` also starts the host bridge to the Claude
Code and Codex command line tools on `127.0.0.1:8189`, and `make down` stops it. That
mode needs uv on the host and both tools signed in with a plan.
`make bridge-status` shows whether they are. The bridge and its contract are described
in [tools/cli_bridge/README.md](tools/cli_bridge/README.md).

Open http://localhost:3000 for the interface. Every published port binds to `127.0.0.1` only. Without `make`: copy `.env.example` to
`.env`, then `docker compose up --build --detach --wait`.

## Build status

[PROGRESS.html](PROGRESS.html) shows milestones, the current cards and what is being built
right now. [PROGRESS.json](PROGRESS.json) holds the same facts for tools and is the
authority: edit it, then run `node tools/sync-progress.mjs`.

## Two rules for this public repository

1. **No secrets.** Only `.env.example` with placeholders is committed. gitleaks runs as a
   pre-commit hook.
2. **No third-party characters or other people's IP.** Every sample and media file is
   original or permissively licensed and has a row in [ASSETS.md](ASSETS.md).
   `scripts/check_assets.py` fails the build when a row is missing.

## Licence

[MIT](LICENSE)
