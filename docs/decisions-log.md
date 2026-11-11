# Decisions log

Decisions the implementing agent took without the owner, following the Unblock protocol in
design doc section 16. Each entry gives the problem, the options, the choice, why, and how
to reverse it. Questions about the design itself are in [questions.md](questions.md).

## D-001: No GitHub repository yet, work continues on stacked local branches

- **Date:** 2026-11-11. **Card:** VFS-1, parked part in VFS-61.
- **Problem:** The project folder had no git repository and no GitHub remote. The session's
  permission guard refused `gh repo create`, for a public repository and then for a private
  one. Without a remote there are no pull requests, no auto-merge and no CI.
- **Options:** (a) stop and wait, (b) find another way to create the repository, (c) keep
  building locally and park the remote for the owner.
- **Choice:** (c). A deliberate guard is not worked around, and waiting is not allowed. Each
  card is built on its own branch `vfs-<id>-<name>`, stacked on the previous card's branch,
  and verified with every local check that exists. `main` holds only the initial commit.
  Finished cards wait In review. VFS-61 is parked in Blocked with the two-minute fix.
- **Consequence:** The rule "dependencies must be Done before a card starts" is read as
  "dependencies must be finished and verified locally" until the remote exists. No card is
  marked Done before its pull request has merged.
- **Reverse:** Create the repository, push `main`, then open the pull requests in Order.

## D-002: Commits use the GitHub no-reply address

- **Date:** 2026-11-11. **Card:** VFS-1.
- **Problem:** No git identity was configured on the machine, and the repository is meant
  to be public, so a personal email address in commits would be published.
- **Choice:** Repository-local identity `nermo-m` with the account's GitHub no-reply
  address. Nothing global was changed.
- **Reverse:** `git config user.name` and `git config user.email` in this repository.

## D-003: One virtual uv project, imports mirror folder paths

- **Date:** 2026-11-11. **Card:** VFS-1. **ADR:** to be written in VFS-9.
- **Problem:** The design fixes the folder layout but not the Python packaging.
- **Options:** (a) one installable package per folder with a `src/` layout, (b) one project
  for the repository with code imported from the root.
- **Choice:** (b). uv manages one locked environment (`package = false`), Python 3.12 is
  pinned, and import paths equal folder paths: `packages.render.resolver`, `apps.api.main`.
  The paths the design names (`packages/render/theme/`, `packages/skills/<name>/SKILL.md`)
  stay exactly as written, and there is one lockfile for api and worker.
- **Why:** Nothing is published as a library, so separate distributions add build steps
  without a benefit. Boundary rules (no vendor SDK outside `packages/adapters/`, no network
  in `packages/render/`) are enforced by lint and tests, not by packaging.
- **Reverse:** Add a `pyproject.toml` per folder and turn the root into a uv workspace.
  Imports would change from `packages.x` to the new package names.

## D-004: Copyright holder in the licence

- **Date:** 2026-11-11. **Card:** VFS-1.
- **Problem:** The MIT licence needs a copyright holder. The GitHub profile has no name.
- **Choice:** "Nermin (nermo-m)", from the design document's owner line and the account.
- **Reverse:** Edit the one line in `LICENSE`. Listed in the Owner inbox as a name to confirm.

## D-005: Scope of the asset check

- **Date:** 2026-11-11. **Card:** VFS-1.
- **Problem:** Rule 2 names `samples/` and theme assets, but also says fixtures, golden
  frames, screenshots, GIFs and the demo video must be original or permissively licensed.
- **Choice:** `scripts/check_assets.py` requires a row for every file under `samples/`
  (README files excepted) and for every media file anywhere in the repository. A row may be
  a glob. The check also fails on an unknown origin, a licence that is not on the permissive
  list, an empty source, and a row that matches no file.
- **Why:** A wider check is the safer reading of rule 2, and stale rows would make the
  registry untrustworthy.
- **Reverse:** Narrow `requires_row` in the script. The tests document each rule.

## D-006: mypy, ESLint and the asset check run as local hooks

- **Date:** 2026-11-11. **Card:** VFS-1.
- **Problem:** Isolated pre-commit environments cannot see the project's own dependencies,
  so an isolated mypy or ESLint would check against different versions than CI.
- **Choice:** Ruff, gitleaks and the basic hooks are isolated. mypy and the asset check run
  through `uv run --locked`, ESLint through `pnpm exec`. A clean clone needs `make setup`
  once (uv and pnpm installed), which the README states.
- **Reverse:** Replace the local hooks with the mirror repositories and list the
  dependencies under `additional_dependencies`.

## D-007: The owner's project standard is applied without the start-up interview

- **Date:** 2026-11-11. **Cards:** VFS-1, VFS-62.
- **Problem:** The owner's company-wide project standard asks for a yes/no interview on
  scope and colours at project start, and for a progress tracker before feature code. The
  owner's instruction for this project is to work unsupervised and never wait.
- **Choice:** The design document already answers the interview, including the colour
  tokens, so the answers are derived from it and recorded in
  [project-contract.md](project-contract.md) for the owner to correct. The progress tracker
  is added as its own card (VFS-62, Order 15) so it lands before any feature code.
- **Reverse:** Edit the contract. Delete the tracker files if the owner does not want them
  in the public repository.

## D-008: Tool versions come from the registries, not from memory

- **Date:** 2026-11-11. **Card:** VFS-1.
- **Problem:** Build rule 10 and the Unblock protocol say the installed or published
  version is the truth.
- **Choice:** Every pinned version was read from PyPI, npm or the tool's GitHub releases on
  the day it was added: uv 0.13.7, Ruff 0.17.4, mypy 2.4.1, pytest 9.2.0, pre-commit 4.7.0,
  ESLint 10.14.0, gitleaks 8.30.1, pnpm 10.20.0, Python 3.12. Dependabot keeps them current
  from VFS-8 on.
- **Reverse:** Not applicable.

## D-009: Progress tracker shape and port

- **Date:** 2026-11-11. **Card:** VFS-62.
- **Problem:** The owner's project standard asks for a tracker (page, JSON twin, local
  server) but leaves the details to each project. The owner's other projects already use
  ports 8090 to 8093 for theirs.
- **Choice:** Port 8094. `PROGRESS.json` is the authority and `tools/sync-progress.mjs`
  writes it into `PROGRESS.html`, with a test and a pre-commit hook that fail on drift. The
  server serves only the two tracker files and two small endpoints (`/__status` for git
  state, `/__mtime` for reload), the same endpoint names the owner's other trackers use. The
  contract identifier is the neutral `progress/1`, because the owner's standard says the
  company name must not appear in a public product without a brief that says so. The page
  uses the design's font names with system fallbacks until the fonts are bundled with the
  web app (VFS-6).
- **Reverse:** Change the `contract` string in `PROGRESS.json` and its test if an aggregator
  needs another identifier. The port is one constant in `tools/progress-server.js`.

## D-010: Smallest runnable services for the Compose card

- **Date:** 2026-11-11. **Card:** VFS-2.
- **Problem:** The Compose card needs four healthy services, but the API, the worker loops
  and the web shell have their own later cards (VFS-5, VFS-4, VFS-6).
- **Choice:** Each service gets the smallest thing that can run and report health: a FastAPI
  app with `GET /api/v1/health`, a worker that touches a heartbeat file read by
  `python -m apps.worker.health`, and a Next.js app with one placeholder page and
  `/healthz`. The later cards grow these, they do not replace them.
- **Other choices in this card:**
  - The database is published on `127.0.0.1:5433`, not 5432, because this PC already runs a
    Postgres on 5432. `DB_HOST_PORT` changes it.
  - `docker-compose.yml` refuses to start without `POSTGRES_PASSWORD` from `.env`, so no
    password default is committed. `make up` creates `.env` from `.env.example` when missing.
  - `DATABASE_URL` is built in `docker-compose.yml` from the three `POSTGRES_*` values, so
    the password is written in one place only.
  - TypeScript is pinned to 6.0.3. Version 7 is out, but typescript-eslint 8.72 supports
    only versions below 6.1.
  - The API tests use `httpx2`, which the installed Starlette asks for in place of `httpx`.
  - Images run as non-root users. `0.0.0.0` appears only inside containers. The host side
    of every published port is `127.0.0.1`, and a test enforces it (NFR-02).
- **Not done here:** The `LAN_ACCESS=true` half of NFR-02 needs a password session in the
  API and the web app. It is a separate Backlog card (VFS-63).
- **Reverse:** Each item is one line in `docker-compose.yml`, `.env.example` or a
  `package.json`.
