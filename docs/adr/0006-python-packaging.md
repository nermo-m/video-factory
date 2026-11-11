# ADR 6: One Python project, imports mirror folder paths

## Status

Accepted, 2026-11-11. Fills a gap in the design document, see question Q-006.

## Context

The design document fixes the folder layout (`apps/api`, `apps/worker`,
`packages/core`, `packages/render` and so on) and names paths inside it, such as
`packages/render/theme/` and `packages/skills/<name>/SKILL.md`. It does not say how the
Python code is packaged or imported. Nothing in the repository is published as a library.
The api and the worker share most of their code and are built into two images.

## Decision

The repository is one uv project with `package = false`: nothing is built or installed as
a distribution. Code is imported from the repository root, so an import path is the folder
path: `packages.core.queue`, `packages.render.resolver`, `apps.api.main`. Python 3.12 is
pinned in `.python-version`. There is one lockfile, `uv.lock`. Dependencies are split into
groups (`core`, `api`, `worker`, `dev`) and each container image installs only its group.

The boundaries between packages are rules checked by lint and tests, not walls built by
packaging: no vendor SDK outside `packages/adapters/`, no network in `packages/render/`.

## Consequences

- Every path the design document names exists exactly as written.
- One environment and one lockfile for local work, CI and both Python images.
- `uv run` creates the environment from the lockfile on a clean clone, with no build step.
- Tests live beside the code in `tests/` folders and import it the same way production
  code does.
- The top-level names `apps` and `packages` are generic. That is acceptable for an
  application that is never installed next to other code.
- A package cannot be versioned or released by itself. If that is ever needed, this
  decision is replaced.

## Alternatives considered

- **A uv workspace with one distribution per folder and a `src/` layout.** The usual
  choice for libraries. Here it adds a `pyproject.toml` and a build per folder, moves every
  path the design names one level down (`packages/render/src/vfs_render/theme/`), and
  isolates nothing that a lint rule does not already check.
- **Short top-level names (`core`, `render`, `adapters`) with `packages/` on the path.**
  Reads well, but names like `core` collide easily and say nothing about where the code is.
