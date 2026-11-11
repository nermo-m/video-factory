# Video Factory Studio

A self-hosted studio that turns one idea into a finished short vertical video.

A planning model writes a complete, machine-readable Episode Spec. Generation tools produce
images, short clips and narration. A deterministic render engine assembles the video from
the spec. The owner approves the plan and the assets, reviews the result, and uploads the
accepted video by hand. The app never posts anything itself.

> **Status: early development (milestone M0, foundation).** Nothing here produces a video
> yet. This README grows with each milestone and is finished in M8.

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
docs/                plans, decisions and questions
scripts/             repository checks
tools/               progress tracker server and sync
```

## Development setup

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 22 or newer with
[pnpm](https://pnpm.io/), and git. uv installs the pinned Python version by itself.

```bash
make setup        # install Python and Node tooling and the git hooks
make check        # lint, types, unit tests and the asset registry check
make test-integration   # integration tests on a real Postgres (needs Docker)
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
make down         # stop (data volumes are kept)
```

Every published port binds to `127.0.0.1` only. Without `make`: copy `.env.example` to
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
