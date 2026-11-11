.DEFAULT_GOAL := help
.PHONY: help setup lint format types test check-assets precommit check progress

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

types: ## Type-check Python
	uv run mypy

test: ## Run the unit tests
	uv run pytest
	pnpm test

check-assets: ## Fail when a sample or media file has no ASSETS.md row
	uv run python scripts/check_assets.py

precommit: ## Run every pre-commit hook on every file
	uv run pre-commit run --all-files

check: lint types test check-assets ## Run all local checks

progress: ## Serve the build-status page at http://127.0.0.1:8094
	node tools/progress-server.js
