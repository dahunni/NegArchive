# NegArchive — the four commands you actually need (roadmap M3).
#
#   make up       the whole stack in Docker, one command, http://localhost:8021
#   make dev      Postgres in Docker, backend and frontend on the host, reloading
#   make test     pytest against a throwaway Postgres, ruff, tsc
#   make backup   database + managed files into data/backups/
#
# `make help` lists everything.

SHELL := /bin/bash
.DEFAULT_GOAL := help

DATA_DIR ?= ./data
UI_PORT ?= 8021
PY ?= .venv/bin/python
VENV ?= .venv
# Throwaway Postgres for the test suite. A high port, so it cannot collide with
# a real one, and --rm so a crashed run leaves nothing behind.
TEST_DB_PORT ?= 55441
TEST_DB_NAME ?= negarchive-test-db
TEST_DATABASE_URL ?= postgresql+psycopg2://negarchive:negarchive@localhost:$(TEST_DB_PORT)/negarchive

.PHONY: help up down logs dev dev-backend dev-frontend venv test test-py test-db-up test-db-down lint typecheck build e2e backup restore clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- running -----------------------------------------------------------------

up: ## Build and start the whole stack (http://localhost:$(UI_PORT))
	docker compose up --build -d
	@echo
	@echo "NegArchive is starting. UI: http://localhost:$(UI_PORT)"
	@echo "Follow it with: make logs"

down: ## Stop the stack (the data directory is left alone)
	docker compose down

logs: ## Follow the logs
	docker compose logs -f

dev: ## Postgres in Docker, backend and frontend on the host
	@echo "Starting Postgres…"
	docker compose up -d db
	@echo
	@echo "Now run these in two terminals:"
	@echo "  make dev-backend"
	@echo "  make dev-frontend"

dev-backend: venv ## uvicorn --reload on :8010 against the Compose Postgres
	DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:5432/negarchive \
	DATA_DIR=$(DATA_DIR) \
	$(VENV)/bin/uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload

dev-frontend: ## next dev on :3000, proxying to the backend on :8010
	cd frontend && npm run dev

# --- setup -------------------------------------------------------------------

venv: ## Create .venv (Python 3.11) and install the requirements
	@test -d $(VENV) || uv venv --python 3.11 $(VENV)
	@uv pip install --python $(VENV)/bin/python -r requirements.txt -r requirements-dev.txt

# --- checks ------------------------------------------------------------------

test: test-db-up test-py test-db-down ## pytest against a throwaway Postgres

test-db-up:
	@docker rm -f $(TEST_DB_NAME) >/dev/null 2>&1 || true
	@docker run -d --rm --name $(TEST_DB_NAME) -p $(TEST_DB_PORT):5432 \
		-e POSTGRES_USER=negarchive -e POSTGRES_PASSWORD=negarchive \
		-e POSTGRES_DB=negarchive postgres:16 >/dev/null
	@printf 'waiting for postgres'
	@until docker exec $(TEST_DB_NAME) pg_isready -U negarchive -q >/dev/null 2>&1; do printf '.'; sleep 1; done
	@echo ' ready'

test-db-down:
	@docker rm -f $(TEST_DB_NAME) >/dev/null 2>&1 || true

test-py: venv ## pytest only (expects DATABASE_URL, or the throwaway DB above)
	DATABASE_URL=$${DATABASE_URL:-$(TEST_DATABASE_URL)} \
	DATA_DIR=$${DATA_DIR:-$$(mktemp -d)} \
	WATCH_INTERVAL_SECONDS=off \
	$(VENV)/bin/python -m pytest tests -q

lint: venv ## ruff (Python) and eslint (frontend)
	$(VENV)/bin/ruff check .
	cd frontend && npm run lint

typecheck: ## tsc --noEmit
	cd frontend && npx tsc --noEmit

build: ## next build with type errors enabled
	cd frontend && npm run build

e2e: ## Playwright smoke test against a running stack
	cd frontend && BASE_URL=$${BASE_URL:-http://localhost:$(UI_PORT)} npm run e2e

# --- data --------------------------------------------------------------------

backup: ## Database + managed files into $(DATA_DIR)/backups
	./scripts/backup.sh

restore: ## Restore the newest backup (or: make restore ARCHIVE=…)
	./scripts/restore.sh $(ARCHIVE)

clean: ## Remove the preview cache (it is rebuilt on demand)
	rm -rf $(DATA_DIR)/cache
