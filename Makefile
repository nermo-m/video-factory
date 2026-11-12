.DEFAULT_GOAL := help
# Git Bash on Windows rewrites arguments that look like Unix paths ("/export/demo" becomes
# "C:/Program Files/Git/export/demo"). The paths in these recipes are meant for the inside
# of containers, so that rewriting is switched off. Other systems ignore the variable.
export MSYS_NO_PATHCONV := 1
.PHONY: help setup lint format types test check-assets precommit check progress env up down ps logs test-integration migrate noop-job generate-api e2e e2e-update storybook coverage audit secret-scan render-test render-golden-update models voice-test sample-voice demo-render bridge bridge-start bridge-stop bridge-status bridge-flags

help: ## Show the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install Python and Node tooling and the git hooks
	uv sync --locked
	pnpm install --frozen-lockfile
	uv run pre-commit install

lint: ## Lint Python and JavaScript
	uv run ruff check .
	uv run ruff format --check .
	pnpm lint

format: ## Format and auto-fix Python
	uv run ruff format .
	uv run ruff check --fix .

types: ## Type-check Python and TypeScript
	uv run mypy
	pnpm typecheck

test: ## Run the unit tests
	uv run pytest
	pnpm test

test-integration: env ## Run the integration tests against the Compose database
	docker compose up --detach --wait db
	uv run --env-file .env pytest -m integration

migrate: ## Apply database migrations inside the api container
	docker compose exec -T api alembic upgrade head

noop-job: ## Send one no-op job through the queue and wait for the worker to finish it
	docker compose exec -T worker python -m apps.worker.noop_check

generate-api: ## Rewrite apps/api/openapi.json and the typed web client from the API routes
	uv run python -m apps.api.openapi
	pnpm --filter web generate:api

E2E_COMPOSE = docker compose -f docker-compose.yml -f docker-compose.e2e.yml

e2e: env ## Run the browser tests (Playwright and axe) against the stack in the Linux test image
	$(E2E_COMPOSE) up --build --detach --wait db api worker web
	$(E2E_COMPOSE) run --rm --build e2e

e2e-update: env ## Rewrite the approved screenshots after an intended visual change
	$(E2E_COMPOSE) up --build --detach --wait db api worker web
	$(E2E_COMPOSE) run --rm --build e2e --update-snapshots

storybook: ## Browse the interface components at http://127.0.0.1:6006
	pnpm --filter web storybook

coverage: env ## Unit and integration tests with the 80 percent line coverage gate (NFR-04)
	docker compose up --detach --wait db
	uv run coverage erase
	COVERAGE_FILE=.coverage.unit uv run coverage run -m pytest
	COVERAGE_FILE=.coverage.integration uv run --env-file .env coverage run -m pytest -m integration
	uv run coverage combine .coverage.unit .coverage.integration
	uv run coverage report

audit: ## Fail on known vulnerabilities: any in Python packages, high or worse in Node packages
	uv export --locked --all-groups --no-hashes --no-emit-project --format requirements-txt --output-file .audit-requirements.txt
	uvx pip-audit@2.10.1 --requirement .audit-requirements.txt --disable-pip --no-deps
	pnpm audit --audit-level high

secret-scan: ## Scan every commit for secrets with gitleaks (design doc section 13, rule 1)
	docker run --rm --volume "$(CURDIR):/repo" ghcr.io/gitleaks/gitleaks:v8.30.1 git /repo --redact --no-banner

RENDER_IMAGE = docker run --rm --volume "$(CURDIR):/src"

render-test: ## Golden-frame tests inside the pinned worker image
	docker build --quiet --target test --tag vfs-worker-test --file apps/worker/Dockerfile .
	$(RENDER_IMAGE) vfs-worker-test

render-golden-update: ## Approve the frames as they are drawn now (review them before committing)
	docker build --quiet --target test --tag vfs-worker-test --file apps/worker/Dockerfile .
	$(RENDER_IMAGE) --env UPDATE_GOLDEN=1 vfs-worker-test

models: env ## Download the Kokoro voice model files into the models volume (about 340 MB, once)
	docker compose run --rm --no-deps --build worker python -m scripts.download_models --folder /models/kokoro

voice-test: ## Run the real Kokoro voice inside the worker image (needs make models first)
	docker build --quiet --target test --tag vfs-worker-test --file apps/worker/Dockerfile .
	$(RENDER_IMAGE) --volume video-factory_models:/models:ro vfs-worker-test python -m pytest -m voice -p no:cacheprovider

sample-voice: ## Record the sample episode's narration with the real voice (needs make models)
	docker build --quiet --target test --tag vfs-worker-test --file apps/worker/Dockerfile .
	$(RENDER_IMAGE) --volume video-factory_models:/models:ro vfs-worker-test python -m scripts.record_sample_voice

demo-render: env ## Render the sample episode inside the worker image into export/demo
	docker compose run --rm --no-deps --build --user 0 --volume "$(CURDIR)/export:/export" worker python -m apps.worker.demo_render --out /export/demo

check-assets: ## Fail when a sample or media file has no ASSETS.md row
	uv run python scripts/check_assets.py

precommit: ## Run every pre-commit hook on every file
	uv run pre-commit run --all-files

check: lint types test check-assets ## Run all local checks

progress: ## Serve the build-status page at http://127.0.0.1:8094
	node tools/progress-server.js

env: ## Create .env from .env.example when it does not exist
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

# In subscription mode the worker reaches the owner's Claude and ChatGPT plans through
# the host bridge (tools/cli_bridge), so the bridge starts and stops with the stack. The
# other modes never start it and do not need uv on the host for `make up`.
SUBSCRIPTION = grep -q '^PROVIDER_MODE=subscription' .env 2>/dev/null
BRIDGE = uv run --env-file .env python -m tools.cli_bridge

up: env ## Build and start web, api, worker and db, and wait until they are healthy
	docker compose up --build --detach --wait
	@if $(SUBSCRIPTION); then $(BRIDGE) start; fi

down: ## Stop the stack (data volumes are kept)
	docker compose down
	@if $(SUBSCRIPTION); then $(BRIDGE) stop; fi

bridge: env ## Run the host bridge to the Claude Code and Codex tools in this terminal
	$(BRIDGE) run

bridge-start: env ## Start the host bridge in the background (make up does this in subscription mode)
	$(BRIDGE) start

bridge-stop: env ## Stop the host bridge
	$(BRIDGE) stop

bridge-status: env ## Show whether the bridge runs and whether each tool is signed in with a plan
	$(BRIDGE) status

bridge-flags: ## Ask the installed claude and codex whether they accept the bridge's flags (no model call)
	uv run pytest tools/cli_bridge -m host_tools -q

ps: ## Show service status
	docker compose ps

logs: ## Follow the service logs
	docker compose logs --follow
