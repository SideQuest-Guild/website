SHELL := /bin/bash
# =============================================================================
# Variables
# =============================================================================

.DEFAULT_GOAL := help
UV_OPTS ?=
UV      ?= uv $(UV_OPTS)
# The website runs on the Node version pinned in website/mise.toml.
WEB     ?= mise exec -C website --
APP     := sidequest_api.app:create_app

.PHONY: help
help: ## Display this help text for Makefile
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

# =============================================================================
# Setup & Installation
# =============================================================================

##@ Setup & Installation

.PHONY: install install-backend install-frontend install-prek upgrade
install: install-backend install-frontend ## Install backend and frontend dependencies
	@echo "=> Install complete"

install-backend: ## Install the Python workspace (all packages + dev tools)
	@echo "=> Installing backend dependencies"
	@$(UV) sync --all-packages

install-frontend: ## Install the website's Node toolchain and dependencies
	@echo "=> Installing frontend dependencies"
	@mise install -C website
	@$(WEB) npm ci

install-prek: ## Install the prek git hooks
	@$(UV) run prek install
	@echo "=> prek hooks installed"

upgrade: ## Upgrade Python, hook, and website dependencies
	@$(UV) lock --upgrade
	@$(UV) run prek autoupdate
	@$(WEB) npm update
	@echo "=> Dependencies upgraded"

# =============================================================================
# Code Quality
# =============================================================================

##@ Code Quality

.PHONY: lint fmt fmt-check ruff ruff-check type-check type-baseline test coverage
.PHONY: web-lint web-fmt web-fmt-check web-check check-all ci
lint: ## Run every prek hook over the repo (ruff, pyrefly, codespell, oxlint, oxfmt, ...)
	@$(UV) run --no-sync prek run --all-files

fmt: ## Format and autofix Python (ruff) and the website (oxfmt)
	@$(UV) run --no-sync ruff format .
	@$(UV) run --no-sync ruff check --fix .
	@$(WEB) npx oxfmt

fmt-check: ## Check formatting without changing files
	@$(UV) run --no-sync ruff format --check .
	@$(WEB) npx oxfmt --check

ruff: ## Run ruff with fixes (including unsafe fixes)
	@$(UV) run --no-sync ruff check . --unsafe-fixes --fix

ruff-check: ## Run ruff without changing files
	@$(UV) run --no-sync ruff check .

type-check: ## Type check Python with pyrefly (new errors only; known ones live in pyrefly-baseline.json)
	@$(UV) run --no-sync pyrefly check

type-baseline: ## Re-record pyrefly-baseline.json (after fixing or deliberately accepting errors)
	@$(UV) run --no-sync pyrefly check --update-baseline

test: ## Run the Python tests
	@PYTHONDONTWRITEBYTECODE=1 $(UV) run --no-sync pytest -q -W error::DeprecationWarning

coverage: ## Run the Python tests with a coverage report
	@PYTHONDONTWRITEBYTECODE=1 $(UV) run --no-sync pytest -q --cov --cov-report=term-missing --cov-report=xml

web-lint: ## Lint the website with oxlint
	@$(WEB) npx oxlint --deny-warnings

web-fmt: ## Format the website with oxfmt
	@$(WEB) npx oxfmt

web-fmt-check: ## Check website formatting with oxfmt
	@$(WEB) npx oxfmt --check

web-check: ## Type check the website's Astro files and its end-to-end tests
	@$(WEB) npx astro check
	@$(WEB) npx tsc -p e2e

check-all: fmt-check ruff-check type-check web-lint web-check test web-e2e ## Run every check CI runs
	@$(UV) run --no-sync codespell

ci: check-all ## Run all checks for CI

# =============================================================================
# Website
# =============================================================================

##@ Website

.PHONY: web-dev web-build web-preview web-e2e web-e2e-install
web-dev: ## Run the Astro dev server (http://localhost:4321)
	@$(WEB) npm run dev

web-build: ## Build the site to website/dist (served by the API at /)
	@$(WEB) npm run build

web-preview: web-build ## Serve the built site with Astro's preview server
	@$(WEB) npm run preview

web-e2e: web-build ## End-to-end tests: the built site in Chrome and WebKit at desktop and phone sizes (API mocked)
	@$(WEB) npm run e2e

web-e2e-install: ## Download the browsers the end-to-end tests use
	@$(WEB) npx playwright install chromium webkit

# =============================================================================
# Database
# =============================================================================

##@ Database

.PHONY: db-up db-down db-wipe migrate migration
db-up: ## Start Postgres (docker compose)
	@docker compose up -d --wait postgres

db-down: ## Stop Postgres (data kept in the pgdata volume)
	@docker compose down

db-wipe: ## Stop Postgres and delete its volume
	@docker compose down -v --remove-orphans

migrate: ## Apply migrations
	@$(UV) run litestar --app $(APP) database upgrade --no-prompt

migration: ## Autogenerate a migration: make migration MSG="add thing"
	@test -n "$(MSG)" || (echo 'usage: make migration MSG="describe change"' && exit 1)
	@$(UV) run litestar --app $(APP) database make-migrations --no-prompt -m "$(MSG)"

# =============================================================================
# Run
# =============================================================================

##@ Run

.PHONY: api bot dev run-dev
api: ## Run the API (http://localhost:8000, docs at /schema, website at / from website/dist)
	@$(UV) run sidequest-api

dev: ## Run the API + Astro dev server together, proxied through http://localhost:8000 (hot reload, shared cookies)
	@trap 'kill 0' EXIT INT TERM; \
	VITE_DEV_MODE=1 $(UV) run sidequest-api & \
	until [ -f website/.litestar.json ]; do sleep 0.2; done; \
	$(WEB) npm run dev & \
	wait

bot: ## Run the bot (token from DISCORD_TOKEN, else macOS Keychain "discord-mcp")
	@if [ -z "$$DISCORD_TOKEN" ] && ! grep -qE '^DISCORD_TOKEN=.+' .env 2>/dev/null; then \
		export DISCORD_TOKEN="$$(security find-generic-password -s discord-mcp -w)"; \
	fi; \
	$(UV) run sidequest-bot

run-dev: ## How to run everything locally
	@echo "  make db-up && make migrate"
	@echo "  make dev       # API + website hot reload together at http://localhost:8000"
	@echo "  make bot       # Discord bot, in another terminal"
	@echo ""
	@echo "Or run the API and website separately (no proxying, two origins):"
	@echo "  make api       # backend + built site at http://localhost:8000"
	@echo "  make web-dev   # website with hot reload at http://localhost:4321"

# =============================================================================
# Docker Compose
# =============================================================================

##@ Docker

.PHONY: docker-build docker-up docker-down docker-logs docker-ps docker-migrate
docker-build: ## Build the sidequest image (migrate, api and bot share it)
	@docker compose build migrate

docker-up: ## Build, then start Postgres + the API in Docker (the `migrate` service runs first via depends_on)
	@docker compose up -d --build --wait postgres api

docker-down: ## Stop all compose services
	@docker compose down

docker-logs: ## Follow logs from all compose services
	@docker compose logs -f

docker-ps: ## Show compose service status
	@docker compose ps

docker-migrate: ## Apply migrations inside Docker (one-shot `migrate` service)
	@docker compose up --build migrate

# =============================================================================
# Local GitHub Actions (act)
# =============================================================================

##@ Local GitHub Actions

.PHONY: act-list act-ci
act-list: ## List the GitHub Actions jobs
	@act -l

act-ci: ## Run the CI workflow locally with act
	@act pull_request -W .github/workflows/ci.yml --container-architecture linux/amd64

# =============================================================================
# Main
# =============================================================================

##@ Main

.PHONY: clean destroy
clean: ## Remove caches and build output
	@rm -rf .pytest_cache .ruff_cache .coverage coverage.xml htmlcov website/dist website/.astro
	@find . -name '__pycache__' -not -path './.venv/*' -not -path './website/node_modules/*' -prune -exec rm -rf {} +
	@echo "=> Cleaned"

destroy: ## Remove the virtualenv and node_modules
	@rm -rf .venv website/node_modules
	@echo "=> Removed .venv and website/node_modules"
