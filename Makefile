.DEFAULT_GOAL := help
.PHONY: help setup lint format types test check-assets precommit check progress env up down ps logs test-integration migrate noop-job generate-api e2e e2e-update storybook

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
	docker compose exec api alembic upgrade head

noop-job: ## Send one no-op job through the queue and wait for the worker to finish it
	docker compose exec worker python -m apps.worker.noop_check

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

check-assets: ## Fail when a sample or media file has no ASSETS.md row
	uv run python scripts/check_assets.py

precommit: ## Run every pre-commit hook on every file
	uv run pre-commit run --all-files

check: lint types test check-assets ## Run all local checks

progress: ## Serve the build-status page at http://127.0.0.1:8094
	node tools/progress-server.js

env: ## Create .env from .env.example when it does not exist
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

up: env ## Build and start web, api, worker and db, and wait until they are healthy
	docker compose up --build --detach --wait

down: ## Stop the stack (data volumes are kept)
	docker compose down

ps: ## Show service status
	docker compose ps

logs: ## Follow the service logs
	docker compose logs --follow
