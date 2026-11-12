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

- **Date:** 2026-11-11. **Card:** VFS-1. **ADR:** [ADR 6](adr/0006-python-packaging.md).
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

## D-011: Database conventions in the baseline migration

- **Date:** 2026-11-11. **Card:** VFS-3.
- **Problem:** Section 9 names tables and columns but not types, constraints or delete
  behaviour.
- **Choice:**
  - Fixed value sets (states, statuses, kinds) are text columns with CHECK constraints, not
    native Postgres enums. Later milestones add values with an ordinary migration.
  - Money is `NUMERIC(12, 6)`, never a float. Timestamps are `timestamptz`.
  - `id`, `created_at` and `updated_at` have database defaults, so raw SQL inserts work.
    `updated_at` is moved by the ORM on update.
  - Every foreign key is `ON DELETE RESTRICT`: nothing is deleted in v1.
  - Invariants live in the database: one active version per asset (partial unique index),
    a claim's passage cannot be empty (FR-02), costs and counters cannot be negative, a new
    asset starts as `needs_review` so it blocks export until cleared (FR-08).
  - Additions beyond section 9: provider value `demo`, `model_call.billing`, indexes on
    foreign keys, `provider_usage(provider, created_at)` for the rolling windows, unique
    `agent_step(agent_run_id, index)`, `provider_status.provider` and `setting.key`.
  - The api container runs `alembic upgrade head` before it starts, and the worker waits
    for the api to be healthy. The stack stays at four services (D2).
  - Integration tests create one throwaway database per test on the Compose Postgres.
- **Found by the tests:** Alembic's generated `create_table` silently left out the circular
  foreign key `episode.current_spec_id`. The "autogenerate shows no diff" test caught it and
  the migration now adds and drops that key explicitly.
- **Reverse:** Each convention is a follow-up migration. Section 9 remains the reference.

## D-012: Job queue semantics

- **Date:** 2026-11-11. **Card:** VFS-4.
- **Problem:** Sections 4.3 and 4.4 describe the queue in a paragraph. Several details had
  to be fixed to make it safe under concurrency and restarts.
- **Choice:**
  - Claims use `SELECT ... FOR UPDATE SKIP LOCKED` by tag. Gpu claims also take a
    transaction-scoped advisory lock and are refused while any gpu job is running, so the
    one-at-a-time rule holds across processes, not only inside one worker.
  - A claim is identified by the job's `started_at` (taken from `clock_timestamp()`).
    Heartbeat, complete and fail only act while that claim still owns the job. A worker that
    was presumed dead and replaced cannot overwrite the new result. No new column needed.
  - All time comparisons use the database clock.
  - `plan_limit` returns the job to the queue for the reset time (or 10 minutes when the
    tool gave none) and does not count as an attempt.
  - Attempts and backoff: see Q-014. `invalid_output`: see Q-015.
  - The worker is one process with threads: `CPU_WORKERS` cpu loops, one gpu loop and one
    maintenance loop (heartbeats every 10 s, abandoned jobs returned after 60 s). Database
    errors are logged and retried, so the worker survives a database restart.
  - Logs are JSON lines with `job_id` and `episode_id` (NFR-03). Fields whose names look
    like secrets are replaced with `[redacted]` (NFR-01).
  - Settings are read once from the environment into a frozen dataclass and all problems
    are reported together. No new dependency.
- **Reverse:** The constants are at the top of `packages/core/queue.py`.

## D-013: API skeleton, health semantics and the generated client

- **Date:** 2026-11-11. **Card:** VFS-5.
- **Problem:** Section 10 lists what `/health` reports and says the TypeScript client is
  generated and committed, but not how health maps to HTTP status, which generator to use,
  or how the browser reaches the API.
- **Choice:**
  - `/health` answers 200 when the database and the storage work and 503 when either does
    not. ComfyUI is reported (`ok`, `offline`, or `not_needed` in demo mode) but never makes
    the API unhealthy. In demo mode ComfyUI is not contacted at all. Outside demo mode the
    probe result is reused for 10 seconds, because the interface polls every 2 seconds.
  - Every error uses the section 10 shape, including 404, 405, validation errors and
    unhandled exceptions. A 500 response is generic: the stack trace goes to the log only.
  - The OpenAPI document is committed at `apps/api/openapi.json`. The client in
    `apps/web/src/api/generated/` is produced by `@hey-api/openapi-ts`. openapi-typescript
    was the first choice but supports only TypeScript 5. Operation ids are the route
    function names, so client functions read `getHealth`.
  - Drift is caught twice: a pytest contract test compares the committed OpenAPI file with
    the app, and `pnpm --filter web check:api` regenerates the client into a temporary
    folder and compares. Both also run as pre-commit hooks. `make generate-api` rewrites
    both.
  - A schemathesis test checks that the running app answers the way its OpenAPI document
    says.
  - The browser talks only to the web origin. Next.js forwards `/api/v1` to the API
    (`API_INTERNAL_URL`), so there is no cross-origin setup.
  - Storage is behind `StorageAdapter` (`packages/core/storage.py`), implemented by
    `LocalStorage`. Paths that leave the root are refused and writes are atomic.
  - The ComfyUI probe uses the endpoint named in the design (`/system_stats`). It has not
    been confirmed against a real ComfyUI, which needs the owner's PC (risk R2, card VFS-29).
- **Found by the tests:** a service on the probed port that does not speak HTTP made the
  probe raise. It now reports "not reachable". Integration tests used to hang when Postgres
  was down. They now stop within seconds and say how to start it.
- **Reverse:** The generator is one dev dependency and one script. The status mapping is in
  `apps/api/health.py`.

## D-014: Web app shell

- **Date:** 2026-11-11. **Card:** VFS-6.
- **Problem:** `docs/design/` had no mockup images, and the card leaves the front-end
  toolchain and several details open.
- **Choice:**
  - Mockups were read from the linked design canvas (artboards for the design system, Board
    on desktop and Board on a phone). Where they differ from the written spec they win: the
    brand in the strip reads "Video Factory", Board columns are Needs you, Planning,
    Producing and Finished (four, not five), the phone merges the middle two into
    "In progress", and the strip says "GPU ready" for ComfyUI.
  - Tailwind CSS 4 with the section 11.1 tokens as CSS variables. shadcn/ui (Radix base)
    supplies button, tooltip and sheet, with its semantic colours mapped onto the tokens.
    The interface is dark only.
  - Fonts come from the `@fontsource-variable` packages (Inter, Space Grotesk, JetBrains
    Mono, all OFL-1.1). Nothing is fetched from Google at build or run time, and no font
    file is committed.
  - The layout switches in CSS, not JavaScript: bottom bar under 640 px, 64 px rail up to
    1023 px, 232 px sidebar from 1024 px, collapsible to the rail and remembered.
  - One primary action per screen: New episode lives in the navigation (sidebar, rail or
    floating button), so the empty Board does not repeat it.
  - The status strip reads `/health` every 10 seconds and pauses while the tab is hidden.
    Running jobs and items waiting for the owner show zero until the jobs and episodes
    endpoints exist (M2). Videos, Library, Jobs, Settings and New episode are honest
    placeholder pages that say what will be there.
  - Browser tests run in the pinned Playwright Linux image against the Compose stack
    (`make e2e`), and the approved screenshots are made there too (`make e2e-update`), so
    they do not depend on the machine. Outside Linux the screenshot comparison is skipped.
  - `@axe-core/playwright` is licensed MPL-2.0, which is weak copyleft, not permissive. It
    is used because the design names axe for the accessibility checks (section 14.1,
    UX-05). It is a test-only tool and no part of it is shipped. Flagged for the owner.
  - Storybook 10 with the Next.js Vite framework, telemetry off, stories for the status
    strip, the navigation and the empty state at phone, tablet and desktop size.
- **Found by the tests:** rail tooltips never opened because the link did not pass the
  tooltip's props on, and rail targets were 43 px wide, one short of the 44 px minimum.
- **Not done:** Next.js lint rules (`eslint-config-next`) and component unit tests with
  Vitest are left for the CI card to decide. Storybook is built locally, not yet in CI.
- **Reverse:** tokens are in `apps/web/src/app/globals.css`, navigation items in
  `apps/web/src/components/shell/nav-items.tsx`.

## D-015: CI workflow written and checked locally, not yet run on GitHub

- **Date:** 2026-11-11. **Card:** VFS-7.
- **Problem:** Section 14.2 lists ten required jobs, but there is no GitHub repository to
  run them on (D-001), and two of the jobs test things that do not exist before M1 and M2.
- **Choice:**
  - `.github/workflows/ci.yml` has the ten jobs with the names from the design. Every job
    calls a make target or script that also runs on a developer machine, and each of those
    was run here: `make lint`, `make types`, `make coverage`, `make audit`,
    `make secret-scan`, `make e2e`, `make noop-job`, `scripts/check_assets.py`,
    `scripts/check_commits.py`. The workflow file passes actionlint.
  - The 80 percent line coverage gate (NFR-04) is applied to unit and integration coverage
    together, in the `integration` job. Unit tests alone reach 64 percent because the queue,
    the worker and the migrations need a real Postgres. Together it is 88 percent.
  - `render` builds the worker image and looks for render tests. While there are none it
    passes with a visible notice. As soon as one exists it fails until the job is wired up,
    so it can never pass silently.
  - `e2e-demo` starts the stack in demo mode, runs the no-op job and the browser tests,
    and uploads screenshots, traces and logs. The idea-to-export run is added in M2.
  - `secret-scan` runs gitleaks from its container image over every commit. A planted fake
    token, committed and then deleted in a later commit, made it fail on a scratch clone.
  - `deps-audit` fails on any known vulnerability in Python packages and on high or worse
    in Node packages. Three high advisories in `js-yaml` (pulled in by the API client
    generator) were fixed with an override to 4.3.2. Two moderate advisories (glob through
    Storybook, minimatch through ESLint) and one low remain and are left to Dependabot.
  - `commit-lint` uses `scripts/check_commits.py` (standard library, tested) on the pull
    request's commits and its title, because squash merges put the title on main.
  - Actions are pinned to commit SHAs. The CI database uses trust authentication so no
    password is written in the workflow.
- **Not proven:** "CI is green on the skeleton" needs GitHub. The card is parked with
  VFS-61. The first real run will probably need small fixes, which is normal for a
  workflow that has only been linted.
- **Reverse:** Not applicable. The gate threshold is `fail_under` in `pyproject.toml`.

## D-016: Delivery workflows written, publishing and protection parked

- **Date:** 2026-11-11. **Card:** VFS-8.
- **Problem:** Both done-when lines need GitHub: publishing `edge` images on a merge to
  main, and branch protection confirmed by the owner. There is no repository yet (D-001).
- **Choice:**
  - `release.yml` pushes web, api and worker images to the GitHub Container Registry as
    `ghcr.io/<owner>/video-factory-<service>`: commit SHA and `edge` on a merge to main,
    version and `latest` on a `vX.Y.Z` tag, plus a GitHub release with generated notes
    and `docker-compose.release.yml`. The demo video is attached from M8.
  - `nightly.yml` runs the whole CI workflow on a schedule (end-to-end demo run and
    dependency audit are jobs of it) and CodeQL for Python, TypeScript and the workflows.
  - `dependabot.yml` updates uv, npm, Docker, Compose and Actions weekly, with `build(deps)`
    and `ci(deps)` titles that pass commit-lint, and groups minor and patch updates.
  - `docker-compose.release.yml` is the development file with published images in place
    of builds. A test keeps the two files in step.
  - `scripts/protect_main.sh` holds the `gh` commands for the settings in sections 13 and
    14.3: pull requests only, the ten CI jobs required, linear history, squash merges,
    secret scanning and push protection. It has not been run. The agent or the owner runs
    it once the repository exists and CI has run once.
- **Checked:** actionlint on all three workflows, shellcheck on the script,
  `docker compose config` on the release file.
- **Reverse:** Not applicable until the first run.

## D-017: Shape of the JSON Schemas

- **Date:** 2026-11-11. **Card:** VFS-10.
- **Problem:** Section 5 gives one example and a list of rules. The schemas need every
  field, limit and required list spelled out.
- **Choice:**
  - Six files, as the design lists them, in JSON Schema draft 2020-12. Shared definitions
    are referenced across files (`claim` lives in the claims schema, `format`, `voice`,
    `stat` and the asset enums in the authored spec), not copied.
  - Every object rejects unknown properties. A model that invents or misspells a field
    fails validation instead of being silently ignored (risk R7).
  - Text lengths and counts have upper limits taken from what fits on a 1080 by 1920 frame
    and a 60 second video. They are first guesses and will move when the renderer exists.
  - The resolved spec keeps the authored structure, with every `cue` replaced by `at_s`
    (seconds from the start of the video), a `narration` object with its audio file and
    word timings, and a `file` on every asset. Files must be relative storage paths.
  - Invalid fixtures say where their problem must be reported, and a test checks it, so
    error locations are part of the contract. A field that belongs to another scene kind
    is reported at that field as "'stat' is not allowed here".
  - Open points decided: Q-016 to Q-019.
- **Not in the schemas:** references that must exist (`claim_id`, `asset_id`), unique scene
  ids and word indexes within the narration are checked by the resolver (VFS-11). What the
  theme can draw is checked against `capabilities.json` (VFS-12).
- **Reverse:** A schema change is a new `spec_version` and a fixture update.

## D-018: Resolver rules

- **Date:** 2026-11-11. **Card:** VFS-11.
- **Problem:** Section 5.2 gives the resolver's main rules. Edge cases needed deciding.
- **Choice:**
  - `resolve(authored, voice, files)` is a pure function in `packages/render/resolver.py`.
    It validates the authored spec first and the resolved spec before returning it.
  - An event without a cue happens when its scene starts.
  - An outro lasts pad before, narration, pad after, then `hold_s`, which defaults to
    2 seconds (the design asks for the closing line to be held for 2 seconds).
  - A silent scene (empty narration) has no pads and no audio. Its length is `duration_s`.
  - With `duration_s` set, the narration must still fit (pad before plus speech), or it is
    a problem, because cut-off speech is never what the author meant.
  - Every event must fall inside its own scene. An event after the scene ends is reported
    with the scene's time range, so the author can raise `pad_after_s`.
  - The tolerance is inclusive: exactly 2 seconds off is accepted. The error lists every
    scene with its length, longest first when the video is too long and shortest first
    when it is too short.
  - Problems are collected and reported together, each with a JSON pointer: duplicate
    scene id, unknown `asset_id` or `claim_id`, a word cue past the end of the narration,
    missing voice timings, voice timings that do not match the narration, an asset without
    a file (FR-05) or without any licence.
  - Times are rounded to milliseconds.
- **Also changed:** the CI `render` job now looks for tests marked `render` (the
  golden-frame and audio tests that must run in the worker image) instead of any test file
  under `packages/render`. The resolver tests are ordinary unit tests.
- **Reverse:** The defaults are constants at the top of the module.

## D-019: The night_scrolls theme and its assets

- **Date:** 2026-11-11. **Card:** VFS-12.
- **Problem:** The theme needs artwork, sounds and fonts, and rule 2 allows nothing that is
  not original or permissively licensed.
- **Choice:**
  - Every image and sound is made by code in this repository,
    `packages/render/theme/night_scrolls/build_assets.py`, from a fixed seed: night sky,
    village silhouette, parchment, scroll roller, lantern, moon, pin, and five sound cues
    (paper unroll, stamp, pin hit, smoke, slam). Running the script again gives identical
    files. Nothing is traced, sampled or generated by an outside model, so the assets are
    original by construction. They are committed, so rendering never needs the script.
  - Fonts are the only third-party files: Anton (slam text), Inter (captions and labels)
    and Kalam (handwritten tags), all OFL-1.1, from the Google Fonts repository, bundled
    with their licence texts and loaded by path (RN-10).
  - `capabilities.json` lists what the theme can draw. `check_capabilities` rejects a spec
    that asks for anything else and names what is available instead. Scene kinds and
    overlay types must equal the schema's lists, which a test checks.
  - `theme.json` holds palette, fonts, layout boxes and asset paths. The scroll, caption
    and slam boxes sit inside the safe area of RN-07, which a test checks.
  - Sprite actions (`sway`, `rise`, `glow`), text styles (`slam`, `slam_accent`), stamp
    colours (`ink`, `red`) and transitions (`smoke`, `cut`) are a first set. The compositor
    card draws them, and may add to the list.
- **Taste decision for the owner:** this is the first look of the videos. The artwork is
  deliberately simple and can be redrawn by editing one script. Look at the files under
  `packages/render/theme/night_scrolls/assets/` and say what should change.
- **Reverse:** Edit the script and run it, or replace any file and its `ASSETS.md` row.

## D-020: How the compositor draws and how golden frames are compared

- **Date:** 2026-11-12. **Card:** VFS-13.
- **Problem:** Section 7.1 names the primitives and says the compositor "draws frame N of
  scene S", but not the layout coordinates, the animation lengths, how a frame is made
  smaller for preview mode, or how strict a golden-frame comparison is.
- **Choice:**
  - Every frame is drawn on a 1080 by 1920 canvas and scaled to the spec's frame size at
    the end. Preview mode (RN-12) therefore shows the same layout, only smaller.
  - The compositor has no clock and no unseeded randomness. Every random effect (drifting
    motes, shake, smoke) takes the spec's `seed` plus a fixed key, so a frame depends only
    on the resolved spec, the theme and the asset files (FR-11). A test renders twice and
    compares.
  - Animation lengths are constants in the code: scroll unroll 0.6 s, smoke 0.35 s at each
    end of a scene, slam 0.14 s, shake 0.3 s. Smoke is drawn inside the outgoing and the
    incoming scene from the same seeded cloud, so the two files meet fully covered (RN-03).
  - Text and key art report where they were drawn, and a test fails when any of it enters
    the bottom 15 percent or the right 12 percent (RN-07). Background artwork is exempt.
  - Caption groups also end where a sentence ends, on top of the 3 word and 14 character
    limits of RN-06, and a caption stays for 0.35 s after its last word.
  - A clip is passed in as decoded frames. After its last frame it freezes, or loops when
    asked (RN-08). Decoding a clip file with FFmpeg belongs to the encode card (VFS-16).
  - Golden frames are stored at 270 by 480. A frame passes when the mean difference is at
    most 1.2 levels and at most 0.4 percent of pixels differ by more than 24 levels. A
    failed frame is written to `packages/render/tests/failed/` and uploaded by CI.
  - Golden tests carry the pytest marker `render` and run only inside the `test` stage of
    the worker image (`make render-test`), which the CI `render` job now calls.
- **Measured:** 29 to 95 ms per full-size frame on the owner's PC, one process. A 45 second
  episode is 1350 frames, so drawing is well inside the RN-11 budget before encoding.
- **Reverse:** The constants sit at the top of `compositor.py`, `primitives.py` and
  `text.py`. After a visual change run `make render-golden-update` and review the frames.

## D-021: The voice adapter

- **Date:** 2026-11-12. **Card:** VFS-14.
- **Problem:** The design names Kokoro but not a library, says word timings are estimated
  per sentence without saying where a sentence's audio time comes from when a scene is
  spoken as one passage, and says the twin "returns bundled sample audio" without saying
  for which text.
- **Choice:**
  - **Library.** The `kokoro-onnx` package needs GPL-3.0 packages, which the build rules do
    not allow. The adapter runs the model with ONNX Runtime directly and starts the
    `espeak-ng` program as a separate process for phonemes. Full reasoning in
    [ADR 7](adr/0007-kokoro-without-gpl-dependencies.md).
  - **Model files.** `kokoro-v1.0.onnx` (326 MB) and `voices-v1.0.bin` (28 MB) from the
    kokoro-onnx release page, pinned by SHA-256 in `scripts/download_models.py`.
    `make models` downloads them inside the worker container into the named volume
    `models`, because decision D9 keeps data in named volumes and a guard test enforces
    it. They are never committed.
  - **Checked against the real model** (build rule 10): inputs `tokens`, `style` and
    `speed`, audio out at 24 kHz, no timestamps. 7.7 seconds of speech take about 4 seconds
    on the owner's CPU. The same request gives byte-identical audio.
  - **Word timings.** The pauses in the audio are measured (quiet for at least 80 ms).
    First every punctuation mark is matched to a pause, longest pauses first. If the audio
    has too few pauses, or the match would make a phrase 2.5 times faster or slower than
    the passage, only sentence ends are matched. If that fails too, the whole passage is
    shared by letter count with extra weight after punctuation. On the real voice the first
    attempt succeeded on every test narration and word times met every measured pause.
  - **One timing per whitespace-separated word**, with the word as written, because the
    resolver counts words that way and refuses a mismatch.
  - **Pronunciation dictionary.** Whole words, any case, phonemes in the model's alphabet.
    An inflected form ("Nermin's") needs its own entry. A dictionary with characters the
    model does not know is refused before anything is synthesised, naming the word.
  - **The twin.** `SampleVoice` returns a recording made earlier with the real voice, found
    by a key of text, voice, speed and the dictionary words used. Narration with no
    recording is refused with the instruction to run `make models`: a silent or wrong
    voice would be worse than a clear error. The recordings for the sample episode are
    made in VFS-17.
  - **Live tests.** `make voice-test` runs the real voice inside the worker image. It is
    not a CI job: it needs the 354 MB download on every run, and the design puts real
    providers at the "Live" test level. CI covers the adapter with a stand-in model.
  - **Voices.** English only (D5): names starting `af_`, `am_`, `bf_`, `bm_`. British
    voices are phonemised as British English.
- **Reverse:** The adapter is behind `TTSAdapter`. Another engine, or forced alignment for
  timings, replaces one module and keeps the `Narration` it returns.

## D-022: The audio mix

- **Date:** 2026-11-12. **Card:** VFS-15.
- **Problem:** RN-09 gives three limits (voice at least 10 dB above music while speaking,
  about -14 LUFS, true peak under -1 dB). The design does not say where the music comes
  from, what format the mix has, how levels are set, or how loudness is measured.
- **Choice:**
  - **Format.** 48 kHz stereo, exactly as long as the video. Narration (24 kHz) and the
    theme's sound cues (44.1 kHz) are converted when they are placed. Loudness is measured
    on the final stereo signal, because that is what a platform measures.
  - **Three stems that add up to the mix:** voice, effects and music. The tests measure
    the limits on the stems and the mix themselves, not on the mix's own report.
  - **Music bed.** The theme had no music and nothing third-party may be added. The bed is
    a soft sustained chord synthesised at mix time from two settings in `theme.json`
    (`notes_hz` and `brightness`), with slow swells decided by the spec's seed. It adds no
    file to the repository, has no loop seam and is as long as the video.
  - **Levels follow the voice.** Music under speech sits 14 dB below the quietest scene's
    voice, which leaves 4 dB of room over the 10 dB of RN-09. Between narrations it comes
    up by 6 dB, over half a second, and is down again 50 ms before the next word. Pauses
    shorter than about a second do not bring it up. A sound cue peaks 6 dB above the
    voice's average level, moved by its `gain_db`.
  - **Loudness.** Measured in NumPy after ITU-R BS.1770-4 (K-weighting, 400 ms blocks,
    absolute and relative gates), checked against the EBU Tech 3341 reference signals. True
    peak is found by oversampling four times. The mix is brought to -14 LUFS, then a
    look-ahead limiter keeps peaks down, and both are measured again and corrected until
    the mix is inside both limits.
  - **A second opinion.** A render test writes the mix to a file and has FFmpeg's
    `ebur128` meter measure it inside the worker image. FFmpeg and this project's meter
    agree within 0.2 LU, so FFmpeg is now in the worker image. That adds about 600 MB to
    the image. A slimmer FFmpeg build is possible later if image size matters.
  - **Timeline.** `packages/render/timeline.py` is the flat, time-ordered event list of
    section 7.1. The mix reads narration and sound events from it. The contact sheet
    (VFS-16) will use it to find a scene's busiest moment.
- **Found on the way:** installing FFmpeg changed ten golden frames. FFmpeg's packages
  bring the FriBiDi library, and Pillow then switches its text layout to Raqm without being
  asked, which moves letters by a pixel or two. `text.load_font` now asks for the basic
  layout engine by name, with a test, and every golden frame passes unchanged. Without
  this, the same spec would have rendered differently depending on what else was installed.
- **Measured:** mixing a 23 second video takes about 4 seconds. Result on the test episode:
  -14.0 LUFS, true peak -3.2 dB, voice 13 dB above the music.
- **Taste decision for the owner:** the music bed is a plain synthesised chord (A minor),
  chosen because it is original by construction. Listen to it in the demo video once
  VFS-17 is done. Changing the notes is one line in `theme.json`. A composed track needs a
  file with a licence and a small extension of the mix.
- **Reverse:** all levels and times are constants at the top of `packages/render/audio.py`.

## D-023: Scene files, joining, preview and the contact sheet

- **Date:** 2026-11-12. **Card:** VFS-16.
- **Problem:** RN-02 to RN-05 and FR-12 say what must hold (one file per scene, joined by
  copying, only changed scenes encoded again, temporary names) but not how a changed scene
  is recognised, which encoder settings are used, or what "busiest moment" means.
- **Choice:**
  - **Scene key.** A scene file is named `scene_<index>_<id>_<key>.mp4`. The key is a hash
    of everything that can change the scene's pixels: the scene, the transition coming in
    from the scene before, format, seed, the picture or clip file's contents, the claim
    behind a statistic, every file of the theme and the drawing code itself. A file that
    exists under its final name is finished, so "is the file there" is the whole check.
    Nothing has to be remembered between renders.
  - **What counts as changed.** Times in the resolved spec are absolute. When a scene gets
    longer, the scenes after it start later and have new keys, because their drifting
    background is at a different point. An edit that keeps the timing (text, an overlay, a
    picture) re-encodes one scene. Changing a transition re-encodes the two scenes it is
    drawn in (RN-03).
  - **Encoder.** `libx264`, preset medium, CRF 18, yuv420p, tagged and converted as BT.709.
    Scene files have no sound. The join uses FFmpeg's concat demuxer with stream copy and
    gives every scene's exact length, which keeps frames evenly spaced across joins. The
    audio mix is encoded once, as AAC 192 kbps, and the index is moved to the front
    (faststart). Checked against FFmpeg 5.1 in the worker image (build rule 10).
  - **Temporary names.** Scene files, the audio mix, the video and the contact sheet are
    all written as `<name>.partial.<ext>` and renamed when complete (RN-05).
  - **Preview** is the same spec with the format replaced by 540 by 960 at 15 fps. Its
    scene files have their own keys, so previews and full renders never mix.
  - **Parallel scenes.** `render_scenes(workers=N)` encodes scenes in separate processes
    (spawned, not forked). In the pipeline the worker's `render.scene` jobs do the same
    through the queue.
  - **Contact sheet.** One 270 by 480 tile per scene, JPEG. A scene's busiest moment is
    0.6 seconds after its last element arrived, never inside the smoke of a transition,
    and never while something is still landing: if the last element arrives too late to
    settle, the moment just before it is used.
  - **Clips.** A clip file is decoded with FFmpeg into frames (at most 600) and handed to
    the compositor, which scales, crops and freezes it as built in VFS-13 (RN-08).
- **Found on the way:** each scene's frame count was `round(duration x fps)`. Rounded
  scene by scene, the picture ran up to half a frame per scene ahead of or behind the
  sound, a full frame on the test episode at 15 fps. Scenes now start and end on the frame
  nearest to their time (`scene_frame_counts`), so the total is exact.
- **Measured** in the worker image on the owner's PC: the 23 second test episode at full
  size with 4 workers takes 27 seconds including the audio mix and the contact sheet.
- **Reverse:** encoder settings are one list at the top of `packages/render/encode.py`.

## D-024: The sample episode and `make demo-render`

- **Date:** 2026-11-12. **Card:** VFS-17.
- **Problem:** The design describes the sample ("The Lighthouse Keeper", original, 45
  seconds, no statistic) but not its scenes, where its pictures and narration come from, or
  what `make demo-render` does step by step.
- **Choice:**
  - **The story** has seven scenes: a title hook, four scroll scenes (the climb, the lamp,
    the storm, the light), a steps scene and an outro. With the recorded narration it is
    44.2 seconds long. Every tag, stamp and step lands at least 0.9 seconds before its
    scene ends, so nothing arrives under the smoke. A test keeps that true.
  - **Pictures.** Four flat illustrations drawn by `scripts/sample_pictures.py` from code
    and a fixed seed, like the theme's artwork. A test fails when a committed picture is
    not what the script draws.
  - **Narration.** Recorded once with the real Kokoro voice (`make sample-voice`) and
    committed in `samples/voice/` (1.7 MB). The demo uses the live voice when the model is
    installed and these recordings when it is not, so it needs no download (FR-16).
    `ASSETS.md` lists them as generated by the Apache-2.0 model from this project's text.
  - **The command** runs in the worker image through Compose: check the spec against the
    schema and the theme, copy the pictures, speak or load the narration, resolve, render
    at full size with 4 workers, then probe the finished file and compare it with RN-01.
    It exits with an error when a check fails. The output goes to `export/demo/` on the
    host, which is ignored by git.
  - **Format checks** live in `packages/render/probe.py`: size, frame rate, codecs, pixel
    format, audio bitrate, sample rate and channels, faststart, exact frame count and
    length. The fuller quality checks of FR-13 belong to milestone M4.
  - **Windows.** Git Bash rewrites arguments that look like Unix paths before Docker sees
    them. The Makefile switches that off for its recipes (`MSYS_NO_PATHCONV`).
- **Measured (RN-11):** 53 seconds with 4 workers and 94 seconds
  with 1, against a target of 6 minutes. The numbers are in the README.
- **Taste decision for the owner:** this is the video a visitor of the repository sees
  first. Watch `export/demo/video.mp4` after `make demo-render`. The wording is in
  `samples/lighthouse_keeper/episode_spec.json`, the pictures in one script.
- **Reverse:** edit the spec or the script, run `make sample-voice` if narration changed.

## D-025: The pipeline state machine

- **Date:** 2026-11-12. **Card:** VFS-18.
- **Problem:** Section 4.2 gives four transition rules. It does not say who notices that a
  state's jobs have all succeeded, how the jobs of one run of a state are told from an
  earlier run, where stale scenes are kept, or what exactly "visual" and "timing" cover.
- **Choice:**
  - **Who moves the episode.** The rules live in `packages/core` (`stages.py`, `stale.py`,
    `pipeline.py`), so the api and the worker use the same code. The worker calls
    `pipeline.job_succeeded` in the transaction that stores a job's result. An episode then
    runs from the idea to the next gate without anyone polling, also with the browser
    closed. Section 3.2 says "api advances the state machine": the api keeps the owner's
    actions (advance, approve, reject, re-run, card VFS-22), the automatic step is the
    worker's. If the pipeline cannot move on, the job still keeps its result and the
    episode waits for `advance`.
  - **Runs and stages.** A state has stages (`asset_gen`: images, then clips. `render`:
    scenes, then join). Every job carries `state`, `stage` and `run` in its input. The
    current run of a state is its highest run number. No new table.
  - **One job per scene** for `gen.voice` and `render.scene`, so a single scene can be made
    again. `gen.image` only for assets whose origin is `generated`, `gen.clip` on the gpu
    queue only for scenes that ask for a clip. A stage with no job is passed over.
  - **Gates** follow `direction`, `asset_gen` and `critique`. With the critic switched off
    (`CRITIC_ENABLED=false`) `critique` has no job and the review gate comes right after
    the checks.
  - **Reject** returns by default to the state that produced what was rejected: the plan to
    `direction`, the assets to `asset_gen`, the video to `render`. It may name an earlier
    state, never a later one. The comment travels in the new jobs' input.
  - **Re-run** cancels the jobs of the current state that had not finished, deletes
    nothing, and sets `stale_from_state` to the first later state that has finished work.
    The marker moves forward when that state is done again.
  - **Stale scenes** are stored in a new column, `episode.stale_scenes` (migration 0002).
    Narration: the scene's text, or the episode's voice settings. Timing: pads, fixed
    duration, hold, and a scene added, removed or moved. Visual or asset: everything else
    a scene shows or plays, a transition (both scenes it touches), and seed, theme and
    format (every scene). `retention_device` is never drawn and marks nothing. Marks are
    only kept for outputs that exist. An edit only marks: nothing runs until a state is
    run again.
  - **`advance`** starts the pipeline from `idea` and otherwise moves on only when the
    current state has finished. At a gate it is refused.
- **Checked:** 37 integration tests on real Postgres, grouped by the rule of 4.2 they
  prove, including two jobs finishing at the same moment. Breaking "all jobs must have
  succeeded" or the gates on purpose makes them fail.
- **Reverse:** the rules are tables at the top of `packages/core/stages.py`.

## D-026: Provider mode and the paid API guard

- **Date:** 2026-11-12. **Card:** VFS-55.
- **Problem:** Section 3.4 says paid APIs need the mode `api` and a Settings switch
  together and that the mode never changes by itself. It does not say where the switch is
  kept, how "refuse to start" is made impossible to forget, or how a test can show that
  "no code path switches mode automatically".
- **Choice:**
  - **Tables in one place.** `packages/core/providers.py` holds who answers in each mode
    and the billing type of each provider. There is no function that maps one mode to
    another, so there is nothing a fallback could call.
  - **The switch** is the row `use_paid_apis` in the `setting` table. Only a stored `true`
    counts. `GET /settings` shows the mode, the switch, whether paid APIs are really on
    and why not, and which secret variables are set, never their values. `PUT /settings`
    changes the switch and nothing else: a body that names the mode is rejected.
  - **The refusal is a constructor.** `PaidApiAdapter` checks mode, switch and key before
    an adapter exists. The key is held in a closure, not in an attribute, so printing the
    adapter or its attributes cannot leak it. Adapters are built per job, so turning the
    switch off takes effect with the next job.
  - **Scans instead of promises.** `tests/infra/test_provider_mode.py` reads the source: no
    code outside `settings.py` assigns or chooses a provider mode, no code writes the
    process environment, the variable is read in one file, settings are frozen, and a
    module that imports the `anthropic` or `openai` SDK must build on `PaidApiAdapter`.
    The scans also bind code that is written later.
  - **Billing in the database.** Migration 0003 adds two CHECK constraints to `model_call`
    and `provider_usage`: the billing type must be the provider's, and only api calls may
    carry a cost.
  - **No paid SDK is installed.** The Anthropic and OpenAI adapters themselves come with
    the cards that need them. This card makes sure they cannot be written without the
    guard.
- **Found on the way:** the contract test that fuzzes the API showed two gaps in the API
  skeleton. A wrong method on an address with two routes named only the first route's
  methods in the `Allow` header, and an unreadable request body answered 400, which was
  not documented. Both are fixed with tests.
- **Reverse:** the tables are at the top of `packages/core/providers.py`.

## D-027: The language model adapter

- **Date:** 2026-11-12. **Card:** VFS-19.
- **Problem:** Section 3.3 names an `LLMAdapter` with the Anthropic API as the real
  implementation and recorded responses as the mock. It does not say what a request and a
  response look like, how a recording is found, how structured output and web search are
  asked for, or how the adapter can be trusted without calling a paid API.
- **Choice:**
  - **One request is one skill call.** `LLMRequest` carries the skill and its version, the
    prompt, an optional output schema and whether the model may search the web.
    `LLMResponse` carries the output, tokens, cost, latency, the provider and model that
    answered, and for research the passages the model really retrieved (FR-02).
  - **Recordings** are one file per skill, `samples/recordings/<skill>.json`, and answer
    whatever the prompt is: demo mode tells one story. A recording is checked against the
    schema and the skill version the caller asks for, so a stale recording fails loudly.
    The recordings themselves arrive with the skills (VFS-20, VFS-21).
  - **Anthropic adapter.** Python SDK `anthropic` 2.8.0 (Apache-2.0). Default model
    `claude-opus-5-5`, effort `medium`, set by `ANTHROPIC_MODEL` and per request.
    Structured output through `output_config.format`, with the constraints the API does
    not enforce removed from the schema that is sent. Web search through the server tool
    `web_search_20260209`, called directly so results and citations are in the answer.
    Search answers always carry citations, which the API refuses together with a fixed
    output format, so a search request asks for JSON in the prompt and it is parsed here.
    A paused search turn is sent back up to three times. Requests opt into the API's
    server-side refusal fallback.
  - **Cost** is computed from the usage the API reports and a price table in the adapter
    (prices of 2026-11-03). A model without a price is refused at start, because its cost
    would be a guess. A web search is one cent.
  - **Errors** map to the queue's classes: rate limits, overload, server errors and
    connection failures are retried, a bad key or unknown model goes to the owner, an
    answer that is not JSON or is cut off is invalid output, a rejected request is a bug.
  - **Tested through the real SDK.** The tests replace only the SDK's HTTP transport, so
    they see the request the SDK really builds. That already corrected one assumption:
    SDK 2.8.0 sends the key as a bearer token with API version 2026-10-21.
  - **Keys and logs.** A test captures every log line of every logger at debug level
    during successful and failing calls and fails if the key appears. The app's own line
    per call carries numbers only. The log redaction now lets `input_tokens` and
    `output_tokens` through, which are counts, while anything else named like a token
    stays hidden.
  - **Model call logging.** `packages/core/usage.py` stores one `model_call` row per call.
    The billing type follows from the provider, and plan and demo calls store cost 0.
  - **Subscription mode** has no language model until the host bridge exists (VFS-56,
    VFS-57). The factory says so and never reaches for the paid API instead.
- **Not verified:** the adapter has not called the live API. No key, and the development
  budget is 0. Card VFS-64 holds the live check and lists what it must confirm, including
  the fallback beta header.
- **Reverse:** another provider is another class behind `LLMAdapter`.

## D-028: The host bridge to the command line tools

- **Date:** 2026-11-12. **Card:** VFS-56.
- **Problem:** Section 3.4 outlines the bridge but leaves open its language, the exact
  flags, how a usage limit is recognised, how sign-in is trusted, and how a service on
  127.0.0.1 is kept away from web pages.
- **Choice:** The full reasoning and every flag are in
  [ADR 8](adr/0008-host-bridge-for-the-command-line-tools.md). In short:
  - **Plain Python, standard library only**, in `tools/cli_bridge/` (underscore, so it can
    be imported). Same type checks, lint rules and coverage gate as the rest.
  - **Flags confirmed against Claude Code 2.1.300 and Codex 0.144.1** by reading the help
    and by running each full command line with an empty prompt, which makes no model call.
    `make bridge-flags` repeats that.
  - **Plan sign-in is checked before every call**, in the cleaned environment. Any other
    sign-in means the tool is not started.
  - **Whole variable prefixes are removed** from a tool's environment (`ANTHROPIC_`,
    `OPENAI_`, `CLAUDE_`, `CODEX_`, and anything with `API_KEY`), with three harmless
    exceptions by name.
  - **A usage limit is read from the tool's own sentence**, with the reset time in the
    PC's clock. The sentences come from the program text of the two versions.
  - **Web pages are refused** by the `Host` header, by `Origin` and `Sec-Fetch-Site`, and
    by accepting only `application/json`. No password between worker and bridge.
  - **Start and stop:** `make up` and `make down` do it in subscription mode. A running
    bridge is found by asking its port, not through a file with a process number, so
    another program on the port is never stopped by mistake.
  - **Contract `bridge/1`** with its error classes is in `tools/cli_bridge/README.md`.
    Both tools answer in the same shape, with input tokens counted the same way.
- **Found while building:** on Windows, Python's HTTP server sets an option that lets a
  second program listen on a port that is already taken, so two bridges could have run
  side by side. The option is off on Windows now, with a test. Asking a closed port takes
  Windows two seconds, so start and stop first try to take the port, which answers at once.
  And a request that was refused before its body was read sometimes never got its answer:
  closing a connection with unread input can drop the answer on its way out (about one
  request in thirty with a large body). The bridge now reads the rest of a request before
  it refuses it, with a test that sends 150 of them.
- **Not verified:** no model call has gone through the bridge. Card VFS-65 holds the live
  check. The sample outputs the fake tools print were written by hand from the tools'
  documented output.
- **Not in this card:** `/codex/image` (card VFS-60 in M3), and letting the critic read
  image files from one folder (M6). The bridge refuses fields it does not know, so neither
  can be used by accident before it exists.
- **Reverse:** the worker only knows the contract. Another implementation behind the same
  contract replaces this one.

## D-029: The adapters that call the host bridge

- **Date:** 2026-11-12. **Card:** VFS-57.
- **Problem:** The card asks for `LLMAdapter` implementations that call the bridge: Claude
  for the planner and the agents, Codex for the second review. It does not say how a
  request maps to the bridge, what happens to output schemas, how the bridge's errors
  reach the job queue, or what a missing bridge is.
- **Choice:**
  - **Two adapters in `packages/adapters/llm/cli_bridge.py`.** `ClaudeCliLLM` posts to
    `/claude`, `CodexCliLLM` to `/codex`. Both refuse to be built unless the mode is
    `subscription`. They use Python's own HTTP client, so the worker gains no dependency.
  - **Schemas.** Claude Code enforces the schema itself. Two cases put the schema into the
    prompt and parse the answer in the adapter: a research call, as in API mode, and every
    Codex call, because Codex only takes schemas in OpenAI's strict form (every property
    required, no extra properties), which this project's schemas are not written in.
  - **Errors** follow section 4.4. `plan_limit` becomes `PlanLimitError` with the reset
    time. `busy`, `timeout`, `tool_failed` and `internal` are retried. `invalid_output` is
    invalid output. A tool that is missing or not signed in with a plan is an owner task
    with the bridge's own instruction. A refused request, or an error class the adapter
    does not know, is a bug.
  - **A bridge that does not answer is an owner task**, like ComfyUI in section 8: the
    message says to run `make bridge-start`. Something else on the port is an owner task
    too. Only a bridge that is there but slow is retried.
  - **Waiting.** The adapter waits for the model call, for the tool's turn and a margin,
    1230 seconds by default, because the bridge holds a request while the tool is busy.
  - **Cost.** A plan call has cost 0, and `cost_text` in `packages/core/providers.py`
    turns a plan call into "covered by plan" for whatever shows costs later.
  - **Models.** `CLAUDE_CLI_MODEL` and `CODEX_CLI_MODEL` are passed on when set. When
    Codex does not say which model answered, the call is recorded as "codex default".
  - **Efforts.** Codex knows three. `xhigh` and `max` become `high`.
  - **Second review.** `Adapters.second_opinion()` is new: recordings in demo mode, Codex
    in subscription mode. API mode has no second reviewer until the OpenAI adapter exists.
- **Not available in this mode:** the passages a web search retrieved. The bridge gets one
  JSON result from Claude Code, without the pages. FR-02 needs them, so research in
  subscription mode waits for card VFS-67, which needs a real run first (VFS-65).
- **Not done in this card:** "the planner skills pass their recorded-response tests through
  the bridge". The skills are built later by Order (VFS-20, VFS-21). Card VFS-66 runs
  that test once they exist. Here the adapters are tested through a real bridge with the
  fake tools, and against a stub that answers with every error class of the contract.
- **Reverse:** another way to reach the tools is another class behind `LLMAdapter`.

## D-030: The usage and limits tracker

- **Date:** 2026-11-12. **Card:** VFS-58.
- **Problem:** Section 3.5 describes the tracker's behaviour and its two tables. It leaves
  open where budgets and overrides are stored, what the default budgets are, which job
  needs which provider, how a waiting job is marked, and how the api service can run the
  check.
- **Choice:**
  - **Rules in `packages/core/limits.py`.** The first half is plain rules without a
    database (windows, budget share, states, the reason a job waits). The second half
    applies them to `provider_usage` and `provider_status`.
  - **Every recorded model call is also a usage row.** `record_model_call` writes both, so
    a skill cannot forget one of them.
  - **What is counted against a budget.** A plan budget is the number of text calls and
    the number of images, each in the 5 hour and the 7 day window. A paid provider's
    budget is dollars in the same two windows. The fullest of them decides: 80 percent
    warns, 100 percent pauses.
  - **Default budgets**, "deliberately low" as the design asks: for a plan 20 calls and 5
    images in 5 hours, 150 calls and 30 images in 7 days. For a paid provider 1 dollar in
    5 hours and 5 dollars in 7 days. The owner changes them with
    `PUT /providers/{id}/budget`.
  - **Budgets and overrides are rows in the `setting` table**, so no new table is needed:
    `budget.<provider>` and `budget_override.<provider>` (the episodes that may continue).
  - **Which job needs which provider** follows from its type: `plan.*` and `agent.*` use
    the text provider of the mode, `asset.image` the image provider, everything else none.
  - **A waiting job** goes back to the queue with error class `plan_limit` and the reason
    as its message, which is what the interface will show. It is not counted as a failed
    attempt. It is tried again at the reset time, or after ten minutes when none is known.
  - **Limit events.** When a job fails with a plan limit, the worker stores the limit on
    the provider in the same transaction, so later jobs wait without asking the tool again.
  - **"Continue anyway" lifts a budget pause, never a limit.** The budget is this app's own
    caution. The limit is the plan's.
  - **The check.** The free check asks the host bridge whether the tool is installed and
    signed in with a plan. The tiny call ("Reply with the single word: ok") is made only
    for a limited provider: by the automatic check once its reset time has passed or when
    it gave none, and by "Check limits now" always. A paid provider is never probed with a
    call. A lifted limit lets the waiting jobs be claimed at once.
  - **The api service runs "Check limits now" itself.** For that it gets `CLI_BRIDGE_URL`
    in Compose, and the Anthropic adapter is now loaded only when asked for, because the
    api image does not install the paid SDK.
  - **API details.** Money travels as text (`"0.50"`), so an amount arrives exactly as
    typed. Budget numbers that each make sense but contradict one another (5 hours above
    7 days) are answered with 409. A second "Check limits now" within 30 seconds is
    answered with 429 and the seconds to wait.
- **Not in this card:** the screens (VFS-59), counting images (the image card in M3), and
  budgets per model. The tables hold the model of every use, so that can be added.
- **Reverse:** budgets are settings rows and can be changed or deleted at any time.

## D-031: What the first live calls through the bridge showed

- **Date:** 2026-11-12. **Cards:** VFS-65 and VFS-67. The owner gave the go-ahead in the
  chat: "I approve everything, continue until we are ready for first videos".
- **What was run:** nine short calls on the owner's plans, with the bridge's own command
  lines: a plain and a structured call to each tool, three research calls to Claude Code,
  and one call through each adapter from inside the worker container. No API key, no money.
- **What held:** every flag, both output shapes, structured answers from both tools, the
  sign-in check, and the path worker container to bridge to tool.
- **What changed:** the bridge now asks Claude Code for its streaming output. The reasons
  and the details are in [ADR 9](adr/0009-the-bridge-reads-claude-codes-streaming-output.md).
  In short: the session's model is read from the session, not guessed. Searches are
  counted from the search results. Retrieved pages come back as `sources`, which is what
  VFS-67 asked for. A call that used an API key fails instead of counting as a plan call.
  The tool's own usage report comes back as `plan_usage`.
- **Corrects Q-044:** Claude Code does report how much of the plan is used, in a form a
  program can read, with every call. Codex does not. The usage tracker does not store the
  report yet. Showing it as "reported by the tool" belongs to the Usage page (VFS-59).
- **Still not seen:** a real usage limit. The turn limits of ADR 8 (4, and 16 with search)
  were enough: a structured answer took 2 turns, a research call 2.
- **VFS-67 is closed with this.** Its third line, the research skill applying FR-02 in
  subscription mode, is the research skill's own work in VFS-20, which now gets sources in
  every mode that has them.

## D-032: The planner service and the first three skills

- **Date:** 2026-11-12. **Card:** VFS-20.
- **Problem:** Section 6 lists the parts of a skill folder and the planner's steps. It
  does not say how a prompt is built, where a skill's version lives, how a skill's own
  rules are applied, what the script's output looks like, or how a skill gets the answer
  of the skill before it.
- **Choice:**
  - **Prompt.** `SKILL.md` is the system prompt, the input as JSON is the prompt. The
    block on top of `SKILL.md` gives the name, the version and whether the skill searches.
  - **The corrective retry** repeats the input and lists what was wrong with the answer.
    An answer the adapter could not read as JSON counts as the first failure too. Both
    calls are returned and stored, because both were made.
  - **FR-02 is applied by the planner, not by the model.** A claim is kept only when its
    address is one of the pages the adapter reports as retrieved. The same page written
    differently (with `www.`, a trailing slash, another case) still counts. Dropped claims
    are named in the job's result. Dropping a claim is not a reason to ask again.
  - **The word budget** is `(target + 2 - 0.7 per scene) x 2.3 x speed`: the design's 2.3
    words per second, the 2 seconds the resolver accepts, and the default pause around a
    scene. A script is sent back when it is more than 5 percent over. The sample episode
    has 97 words against a budget of 96 and renders at 44.2 seconds, so the real voice is
    a little faster than 2.3. The resolver keeps the last word on length.
  - **The script** is a list of scenes with `id`, `beat` (hook, setup, story, fact,
    takeaway, closing) and `narration`, and `claim_ids` where a fact is said.
  - **Job results.** A planning job's output is `{skill, skill_version, document,
    removed}`. The next skill reads `document` of the newest finished job of the type it
    needs.
  - **Recordings** for demo mode tell the sample episode: the recorded script is the
    sample's narration word for word, and the recorded research returns no claim, because
    the story is made up.
- **Order of work, said openly:** for this card the service was written before its tests,
  not after them as the build rules ask. The tests were then checked by putting four
  faults into the code on purpose (keep unsourced claims, a third attempt, a huge slack,
  skip the skill's rules). Each made tests fail.
- **Reverse:** a skill is a folder. Its instructions and schemas change without touching
  the service.

## D-033: The skills direct, assets, package and revise

- **Date:** 2026-11-12. **Card:** VFS-21.
- **Problem:** Section 6 gives each skill one line. It leaves open how the director is
  held to the theme and the script, who fills the fields a model should not decide, what a
  revision looks like, and how a schema that refers to other files reaches a model.
- **Choice:**
  - **The director directs, it does not rewrite.** The spec must keep the script's scenes,
    their order and their narration word for word, so the word budget that the script
    passed still holds. It may only use what the theme declares, checked with the same
    `check_capabilities` the render engine has. An undeclared overlay sends the answer
    back, and fails the job the second time.
  - **The app fills what it knows.** Episode id, format, theme, voice, seed and the claims
    are written into the spec after the model answers. The seed comes from the episode's
    id, so the same episode always draws the same frames.
  - **The spec is stored when it is directed**: a new `spec_version` row, authored by the
    model, pointing at the version before it, and made the episode's current spec. That is
    what the plan gate shows.
  - **A revision is `{summary, patch}`**, a JSON Patch with add, remove and replace. It is
    checked by applying it to a copy: the result must be a valid spec the theme can draw.
    The job returns the patch and applies nothing. Applying it after the owner has seen
    the diff is the episode API's work (VFS-22).
  - **`packages/core/json_patch.py`** is 90 lines of the project's own, so no patch
    library is added.
  - **One self-contained schema per answer.** The shared schemas refer to each other.
    `schemas.bundled_schema` copies what a schema uses from other files into it. Claude
    Code accepts all six that way, which `make bridge-flags` checks without a model call.
  - **The library of reusable pictures** is, until milestone M3 builds the real one, the
    four pictures bundled with the sample episode.
- **Tried live** on the owner's Claude plan: all seven skills in a row for a new idea, each
  accepted on the first try, 110 seconds in all. The directed spec was valid for the
  theme. Its four pictures were planned as generated, which milestone M3 will make.
- **Reverse:** each skill is a folder, each rule one function in `rules.py`.

## D-034: The episode API

- **Date:** 2026-11-12. **Card:** VFS-22.
- **Problem:** Section 10 lists the episode routes in one line each. It leaves open which
  channel a new episode belongs to, where its target length is kept, how a revision that
  needs a model call fits into a quick API, and what the answers look like.
- **Choice:**
  - **Spec changes live in `packages/core/specs.py`.** A spec is never changed in place:
    every change is a new version that points at the one before. The director's answer,
    the owner's edit and an applied revision all go through the same functions, and each
    edit after the plan gate marks its stale scenes through the pipeline.
  - **A revision runs as a job.** `POST /episodes/{id}/revise` queues the revise skill and
    answers 202 with the job. `GET /episodes/{id}/revisions/{job_id}` shows the proposal:
    its summary, its patch and what applying it would change. `POST .../revise/apply`
    applies it. So a revision is counted and waits for a limited provider like every other
    model call, and the API never waits for a model.
  - **A proposal belongs to one version.** It is applied only while the spec is still the
    version it was written for. After any other change it is refused with `spec_changed`,
    because it no longer says what the owner saw.
  - **The read address of a proposal is `/revisions/{job_id}`**, not `/revise/{job_id}`:
    the second would overlap with `/revise/apply`, which the fuzz test caught.
  - **One default channel.** The first episode creates "My channel" with the theme
    `night_scrolls` and the voice `bm_george`. The channel routes of section 10 have no
    card in this milestone.
  - **The episode has its own target length**, 45 or 60 seconds as the New episode screen
    asks, in a new column (migration 0004). Empty means the channel's length.
  - **Errors.** An unknown episode is 404. What the pipeline refuses is 409 with the
    pipeline's own code (`awaiting_approval`, `not_awaiting_approval`, `jobs_unfinished`).
    A spec that is not valid is 422 with every problem listed, including what the theme
    cannot draw.
  - **The Board list is paged** from the start (`limit`, `offset`, `total`).
- **Reverse:** routes are thin. The rules are in `specs.py` and `pipeline.py`.

## D-035: Board and New episode screens

- **Date:** 2026-11-12. **Card:** VFS-23.
- **Problem:** The Board mockups and the written spec differ, the mockups show data the API
  does not have yet, and there is no mockup of New episode.
- **Choice:**
  - **Groups as in the mockups** (D-014): Needs you, Planning, Producing, Finished on
    desktop. Below 1024 px Planning and Producing are one group, In progress. Tablet has
    two columns, Needs you and everything else. On a phone the group headings are buttons
    that fold the group, and Finished starts folded.
  - **An episode at any gate is under Needs you**, with the action in words: Approve the
    plan, Approve the pictures, Review the video.
  - **The progress strip has seven steps**, as drawn: Brief, Research, Script, Direction,
    Pictures, Video, Export. Each covers one or more of the fourteen pipeline states. The
    strip also says its step in words, so it never depends on colour.
  - **Cards are not links yet.** The episode workspace arrives with VFS-24, and a link to a
    page that does not exist would be worse than none.
  - **Not shown yet, because the API has no data for it:** the thumbnail, version and length
    of a rendered video (they come with the render cards), the elapsed time of the running
    job, and a failed job. The count of running jobs in the status strip stays at zero
    until the jobs routes exist.
  - **One episode list for every screen.** A provider in the app shell reads `/episodes`
    every 5 seconds while the tab is visible. The Board shows it and the status strip
    counts what waits for the owner.
  - **A failed load is never an empty Board.** Nothing loaded: an error with the reason and
    Try again. A refresh that fails later: the episodes stay and a note says they may be
    out of date.
  - **50 episodes a page.** With more, the Board says "Showing 50 of 120 episodes" and
    offers Show more.
  - **New episode is the address `/episodes/new`**: the Board with the dialog open over
    it. So the New episode buttons stay plain links, Back closes the dialog, and closing
    leads to the Board. It is a full-screen sheet on a phone and a centred 560 px dialog
    from tablet up, as section 11.5 says.
  - **After Start the Board opens**, not the workspace as the key flow in 11.5 says,
    because the workspace does not exist yet. VFS-24 changes that.
  - **Length defaults to 45 seconds**, the API's default.
  - **Browser tests answer the episode list from a fixed list**, so they do not depend on
    what other tests left in the database. One test goes through the real API and worker:
    New episode on a 390 px screen, and the Board asks to approve the plan.
- **Reverse:** the mapping from states to groups, steps and words is one file,
  `apps/web/src/lib/episodes.ts`.

## D-036: Episode workspace and Plan tab

- **Date:** 2026-11-12. **Card:** VFS-24.
- **Problem:** The Plan tab needs the brief and an estimated length per scene, which no
  route returned. The card says "inline edit" without saying of what, and the mockups show
  a storyboard preview that nothing can draw yet.
- **Choice:**
  - **New route `GET /episodes/{id}/plan`:** the brief, and for each scene its word count
    and estimated seconds, the total, and whether it fits the target.
  - **One estimate for script and plan.** `packages/core/lengths.py` holds the rule the
    script budget already used: 2.3 words per second, 0.7 seconds of pause per scene. A
    silent scene counts its declared length and a hold is added. A plan "fits" inside the
    2 second tolerance widened by 5 percent, because the estimate is not exact. The bar
    says "about", and the voice decides the real length.
  - **Inline edit covers the text of a scene:** narration, title, label, sublabel, the
    on-screen lines of a title or outro scene, and the question it leaves. Pictures,
    overlays, sounds and timing are changed in words or in the raw JSON. An emptied
    optional field is left out of the spec.
  - **Every edit sends the whole spec** to `PUT /spec`, which checks it and stores a new
    version. What the API refuses is shown problem by problem and the edit stays open.
  - **Raw JSON replaces the scene cards** while it is on. It is checked as JSON in the
    browser and against the schema and theme by the API. Below 1024 px it is read only,
    as section 11.5 says.
  - **A change in words** is sent to `POST /revise`, followed until the planner answers,
    and shown as its summary and its changes in plain words ("Scene 1, transition out:
    smoke becomes cut"). Apply stores it. Discard drops it.
  - **The pipeline has eight steps** as in the mockups (Brief, Research, Script, Plan,
    Assets, Voice, Render, Review). The Board strip keeps its seven.
  - **Gate bar:** Approve plan is the one accent action. Request changes needs a comment.
    On a phone the bar sticks above the bottom bar. At the assets and review gates it only
    says what waits, because those screens come later.
  - **Preview:** a placeholder that says the video appears after Render, shown from
    1440 px. No storyboard frame is drawn, and the phone has no mini player yet: there is
    nothing true to show in them before a render exists.
  - **Assets, Voice, Render and Export tabs** say that they are not built yet and when
    they arrive.
  - **Board cards are links now** and Start opens the workspace, as the key flow in 11.5
    says. This closes two follow-ups of D-035.
  - **A source address becomes a link only when it is http or https.** It comes from a
    model's answer.
- **Reverse:** the wording lives in `apps/web/src/lib/workspace.ts`, the estimate in
  `packages/core/lengths.py`.

## D-037: Model picker and Usage page

- **Date:** 2026-11-12. **Card:** VFS-59.
- **Problem:** The card asks for more than the API can answer today: there is no stored
  7 day history, no list of limit events, and no setting for a model per role.
- **Choice:**
  - **Built on what the API has:** `GET /providers`, the budget route, `POST
    /providers/check` and the settings route. Nothing in the API changed.
  - **Usage page at `/settings/usage`:** one card per provider of the current mode, with
    its state, one bar per window and unit against the budget, who counted, when it was
    last checked, and the budget fields. Demo recordings have no budget.
  - **The picker lists the providers it is given.** The API returns only those of the
    current mode, so a paid model appears only in API mode, marked Paid. A limited or
    paused option stays visible with the reason and the return time and cannot be chosen.
    Its two bars show the fuller unit of each window.
  - **The picker is used in Settings as "Models in use", without a choice.** In each mode
    every role has exactly one provider today. Choosing a model per role, and the override
    in New episode, need a setting the API does not have: card VFS-68.
  - **Not built, because nothing stores it:** the 7 day history and the list of recent
    limit events. Card VFS-68 as well.
  - **Words follow the facts:** every count says "Counted by this app". Only a limit a
    tool reported says "Limit reported by the tool". Times are shown in the owner's own
    time zone, with the weekday when more than a day away.
  - **Check limits now** shows that it runs, cannot be pressed twice, and confirms each
    provider that is ready again. The whole answer arrives at once, because the API checks
    all providers in one call.
  - **Use paid APIs asks before it is turned on**, and says that the mode must be `api` as
    well. Turning it off does not ask.
  - **Status strip:** one chip that names the provider and its state, or counts them when
    there are several. Red for limited or paused, yellow for near budget, always with an
    icon and words. It leads to the Usage page.
  - **A budget is set in the unit the API pauses by:** calls and images for a plan, US
    dollars for a paid API. A paid provider shows its calls as a plain count. A budget of
    zero allows nothing, as in the API, so its bar is full after the first use.
  - **One provider list for every screen**, read every 30 seconds while the tab is
    visible, like the episode list.
- **Reverse:** the wording is in `apps/web/src/lib/providers.ts`.
