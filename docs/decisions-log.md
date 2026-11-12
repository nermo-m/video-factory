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
