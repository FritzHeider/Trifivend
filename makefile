# Makefile — two-app Fly.io workflow

SHELL := /bin/bash
.ONESHELL:

APP_NAME_API := ai-callbot
APP_NAME_UI  := trifivend-ui

CONFIG_API   := fly.api.toml
CONFIG_UI    := fly.ui.toml

# Default target
.PHONY: help
help:
	@echo "Targets:"
	@echo "  deploy-api        Build & deploy backend (ai-callbot)"
	@echo "  deploy-ui         Build & deploy UI (trifivend-ui)"
	@echo "  deploy-both       Deploy both API and UI"
	@echo "  logs-api|logs-ui  Tail logs"
	@echo "  status-api|status-ui Show app status"
	@echo "  secrets-api       Push .env as secrets to API"
	@echo "  open-api          Open API in browser"

.PHONY: deploy-api
deploy-api:
	fly deploy --config $(CONFIG_API) --app $(APP_NAME_API)

.PHONY: deploy-ui
deploy-ui:
	fly deploy --config $(CONFIG_UI) --app $(APP_NAME_UI)

.PHONY: deploy-both
deploy-both: deploy-api deploy-ui

.PHONY: secrets-api
secrets-api:
	@echo "Pushing .env -> Fly secrets (skips comments/blank lines)..."
	while IFS='=' read -r key val; do \
	  [[ $$key =~ ^#.*$$ || -z $$key ]] && continue; \
	  fly secrets set "$$key=$$val" -a $(APP_NAME_API) || exit 1; \
	done < .env

.PHONY: logs-api
logs-api:
	fly logs -a $(APP_NAME_API)

.PHONY: logs-ui
logs-ui:
	fly logs -a $(APP_NAME_UI)

.PHONY: status-api
status-api:
	fly status -a $(APP_NAME_API)

.PHONY: status-ui
status-ui:
	fly status -a $(APP_NAME_UI)

.PHONY: open-api
open-api:
	open "https://$(APP_NAME_API).fly.dev/health"