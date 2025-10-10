# ================================================================
# Makefile — TriFiVend x Fly.io (Apps V2)
# ================================================================
SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# --- App Config ---------------------------------------------------
APP_NAME_API ?= ai-callbot
APP_NAME_UI  ?= trifivend-ui

CONFIG_API   ?= fly.api.toml
CONFIG_UI    ?= fly.ui.toml

INTERNAL_HOST ?= ai-callbot.internal
INTERNAL_PORT ?= 8080

# --- Tooling ------------------------------------------------------
OPEN_CMD := $(shell if command -v xdg-open >/dev/null 2>&1; then echo xdg-open; \
                 elif command -v open >/dev/null 2>&1; then echo open; \
                 elif command -v cmd.exe >/dev/null 2>&1; then echo 'cmd.exe /c start'; \
                 else echo echo; fi)

CURL := curl -fsSL
CURL_OK := curl -sS -o /dev/null -w "%{http_code}"

# --- Help ---------------------------------------------------------
.PHONY: help
help:
	@echo ""
	@echo "Fly.io Apps V2 Control Panel"
	@echo "-----------------------------------------------------------"
	@echo "make deploy-api           → Build & deploy backend ($(APP_NAME_API))"
	@echo "make deploy-ui            → Build & deploy UI ($(APP_NAME_UI))"
	@echo "make deploy-both          → Deploy API then UI"
	@echo "make secrets-api          → Push .env → API secrets"
	@echo "make secrets-ui           → Push .env.ui → UI secrets"
	@echo "make logs-api             → Tail backend logs"
	@echo "make logs-ui              → Tail frontend logs"
	@echo "make doctor-api           → Show API machines, logs, and /health"
	@echo "make doctor-internal      → Curl private mesh from UI → API"
	@echo "make set-ui-backend-private → Set BACKEND_URL to internal mesh"
	@echo "make set-ui-backend-public  → Set BACKEND_URL to public domain"
	@echo "make nuke-api | nuke-ui   → Reset machine(s)"
	@echo ""

# --- Guards -------------------------------------------------------
.env:
	@test -f .env || { echo "⚠️  Missing .env (needed for secrets-api)"; exit 1; }

.env.ui:
	@true

# --- Deploys ------------------------------------------------------
.PHONY: deploy-api
deploy-api:
	@echo "🚀 Deploying $(APP_NAME_API)"
	@if grep -q '^\[http_service\]' $(CONFIG_API); then :; else \
		echo "❌ $(CONFIG_API) missing [http_service]"; exit 1; fi
	fly deploy --config $(CONFIG_API) --app $(APP_NAME_API)

.PHONY: deploy-ui
deploy-ui:
	@echo "🚀 Deploying $(APP_NAME_UI)"
	@if grep -q '^\[http_service\]' $(CONFIG_UI); then :; else \
		echo "❌ $(CONFIG_UI) missing [http_service]"; exit 1; fi
	fly deploy --config $(CONFIG_UI) --app $(APP_NAME_UI)

.PHONY: deploy-both
deploy-both: deploy-api deploy-ui

# --- Remote-only builds ------------------------------------------
.PHONY: deploy-api-remote
deploy-api-remote:
	fly deploy --config $(CONFIG_API) --app $(APP_NAME_API) --remote-only

.PHONY: deploy-ui-remote
deploy-ui-remote:
	fly deploy --config $(CONFIG_UI) --app $(APP_NAME_UI) --remote-only

# --- Secrets ------------------------------------------------------
.PHONY: secrets-api
secrets-api: .env
	@echo "🔐 Uploading .env → $(APP_NAME_API)"
	while IFS='=' read -r key val; do \
		[[ $$key =~ ^#.*$$ || -z $$key ]] && continue; \
		fly secrets set "$$key=$$val" -a $(APP_NAME_API); \
	done < .env

.PHONY: secrets-ui
secrets-ui: .env.ui
	@if [ -f .env.ui ]; then \
		echo "🔐 Uploading .env.ui → $(APP_NAME_UI)"; \
		while IFS='=' read -r key val; do \
			[[ $$key =~ ^#.*$$ || -z $$key ]] && continue; \
			fly secrets set "$$key=$$val" -a $(APP_NAME_UI); \
		done < .env.ui; \
	else \
		echo "ℹ️  .env.ui not found; skipping."; \
	fi

# --- Logs / Status / SSH -----------------------------------------
.PHONY: logs-api logs-ui status-api status-ui ssh-api ssh-ui
logs-api: ;	fly logs -a $(APP_NAME_API)
logs-ui:  ;	fly logs -a $(APP_NAME_UI)
status-api: ; fly status -a $(APP_NAME_API)
status-ui:  ; fly status -a $(APP_NAME_UI)

ssh-api:
	@MID=$$(fly machines list -a $(APP_NAME_API) --json | jq -r '.[0].id'); \
	[ -n "$$MID" ] || { echo "❌ no machines"; exit 1; }; \
	fly ssh console -a $(APP_NAME_API) -s $$MID

ssh-ui:
	@MID=$$(fly machines list -a $(APP_NAME_UI) --json | jq -r '.[0].id'); \
	[ -n "$$MID" ] || { echo "❌ no machines"; exit 1; }; \
	fly ssh console -a $(APP_NAME_UI) -s $$MID

# --- Scale --------------------------------------------------------
.PHONY: scale-api scale-ui
scale-api:
	@count=$${N:-1}; echo "📈 Scaling $(APP_NAME_API) → $$count"
	fly scale count $$count -a $(APP_NAME_API)

scale-ui:
	@count=$${N:-1}; echo "📈 Scaling $(APP_NAME_UI) → $$count"
	fly scale count $$count -a $(APP_NAME_UI)

# --- Open / Health / Doctor --------------------------------------
.PHONY: open-api health-api health-ui doctor-api doctor-internal
open-api:
	$(OPEN_CMD) "https://$(APP_NAME_API).fly.dev/health" >/dev/null 2>&1 || true
	@echo "🌐 Opened https://$(APP_NAME_API).fly.dev/health"

health-api:
	@code=$$($(CURL_OK) "https://$(APP_NAME_API).fly.dev/health"); \
	echo "API /health → $$code"; test "$$code" = "200"

health-ui:
	@code=$$($(CURL_OK) "https://$(APP_NAME_UI).fly.dev/"); \
	echo "UI / → $$code"; test "$$code" = "200"

doctor-api:
	@echo "🔬 Machines:"; fly machines list -a $(APP_NAME_API) || true
	@echo "🔬 Last 100 logs:"; fly logs -a $(APP_NAME_API) -n 100 || true
	@echo "🔬 Health:"; $(MAKE) -s health-api || true

doctor-internal:
	@echo "🔎 From $(APP_NAME_UI) → http://$(INTERNAL_HOST):$(INTERNAL_PORT)/health"
	fly ssh console -a $(APP_NAME_UI) -C "curl -sSf http://$(INTERNAL_HOST):$(INTERNAL_PORT)/health || echo '❌ failed'"

# --- Backend URL toggles -----------------------------------------
.PHONY: set-ui-backend-private set-ui-backend-public
set-ui-backend-private:
	fly secrets set BACKEND_URL="http://$(INTERNAL_HOST):$(INTERNAL_PORT)" -a $(APP_NAME_UI)
	@echo "✅ BACKEND_URL → internal mesh"

set-ui-backend-public:
	fly secrets set BACKEND_URL="https://$(APP_NAME_API).fly.dev" -a $(APP_NAME_UI)
	@echo "✅ BACKEND_URL → public https://$(APP_NAME_API).fly.dev"

# --- Nuke Machines ------------------------------------------------
.PHONY: nuke-api nuke-ui
nuke-api:
	@echo "💣 Cycling $(APP_NAME_API) machines..."
	fly scale count 0 -a $(APP_NAME_API); sleep 2
	fly scale count 1 -a $(APP_NAME_API)

nuke-ui:
	@echo "💣 Cycling $(APP_NAME_UI) machines..."
	fly scale count 0 -a $(APP_NAME_UI); sleep 2
	fly scale count 1 -a $(APP_NAME_UI)