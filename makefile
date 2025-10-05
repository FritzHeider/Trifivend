# Makefile — Trifivend x Fly.io (Apps V2)
# -------------------------------------------------------------------
SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# --- Apps & Configs ------------------------------------------------
APP_NAME_API ?= ai-callbot
APP_NAME_UI  ?= trifivend-ui

CONFIG_API   ?= fly.api.toml
CONFIG_UI    ?= fly.ui.toml

# Optional build arg split (monorepo: backend/ui reqs)
REQS_API     ?= /tmp/requirements.backend.txt
REQS_UI      ?= /tmp/requirements.ui.txt

# Internal mesh hostname & port (private IPv6 fdaa::)
INTERNAL_HOST ?= ai-callbot.internal
INTERNAL_PORT ?= 8080

# --- Tooling -------------------------------------------------------
# Cross-platform URL opener (macOS, Linux, WSL)
OPEN_CMD := $(shell if command -v xdg-open >/dev/null 2>&1; then echo xdg-open; \
                 elif command -v open >/dev/null 2>&1; then echo open; \
                 elif command -v cmd.exe >/dev/null 2>&1; then echo 'cmd.exe /c start'; \
                 else echo echo; fi)

CURL := curl -fsSL
CURL_OK := curl -sS -o /dev/null -w "%{http_code}"

# --- Help ----------------------------------------------------------
.PHONY: help
help:
	@echo "Targets:"
	@echo "  deploy-api               Build & deploy backend ($(APP_NAME_API))"
	@echo "  deploy-ui                Build & deploy UI ($(APP_NAME_UI))"
	@echo "  deploy-both              Deploy API then UI"
	@echo "  deploy-api-remote        Deploy API with --remote-only build"
	@echo "  deploy-ui-remote         Deploy UI with --remote-only build"
	@echo "  secrets-api              Push .env -> API secrets"
	@echo "  secrets-ui               Push .env.ui -> UI secrets (if present)"
	@echo "  logs-api | logs-ui       Tail logs"
	@echo "  status-api | status-ui   Show app status"
	@echo "  ssh-api | ssh-ui         SSH into a machine"
	@echo "  scale-api N              Scale API to N machines"
	@echo "  scale-ui N               Scale UI to N machines"
	@echo "  open-api                 Open public API /health in browser"
	@echo "  health-api               Check public API /health (expects 200)"
	@echo "  health-ui                Check UI root (expects 200)"
	@echo "  doctor-api               Machines, last logs, public health"
	@echo "  doctor-internal          From UI box -> curl http://$(INTERNAL_HOST):$(INTERNAL_PORT)/health"
	@echo "  set-ui-backend-private   Set UI BACKEND_URL to private internal mesh"
	@echo "  set-ui-backend-public    Set UI BACKEND_URL to public https://$(APP_NAME_API).fly.dev"
	@echo "  nuke-api                 Scale API to 0, then back to 1 (fresh machine)"
	@echo "  nuke-ui                  Scale UI to 0, then back to 1 (fresh machine)"

# --- Guards --------------------------------------------------------
.env:
	@test -f .env || { echo "⚠️  .env not found (needed for secrets-api). Create it."; exit 1; }

.env.ui:
	@# optional secrets file for UI; not required
	@true

# --- Deploys (Apps V2) --------------------------------------------
.PHONY: deploy-api
deploy-api:
	@echo "🚀 Deploying $(APP_NAME_API) with $(CONFIG_API)"
	@if grep -q '^\[http_service\]' $(CONFIG_API); then :; else \
	  echo "❌ $(CONFIG_API) missing [http_service] (Apps V2)."; exit 1; fi
	fly deploy --config $(CONFIG_API) --app $(APP_NAME_API)

.PHONY: deploy-ui
deploy-ui:
	@echo "🚀 Deploying $(APP_NAME_UI) with $(CONFIG_UI)"
	@if grep -q '^\[http_service\]' $(CONFIG_UI); then :; else \
	  echo "❌ $(CONFIG_UI) missing [http_service] (Apps V2)."; exit 1; fi
	fly deploy --config $(CONFIG_UI) --app $(APP_NAME_UI)

.PHONY: deploy-both
deploy-both: deploy-api deploy-ui

# Remote-only builds (good for M1/M2 mismatches, large cache on Fly)
.PHONY: deploy-api-remote
deploy-api-remote:
	fly deploy --config $(CONFIG_API) --app $(APP_NAME_API) --remote-only

.PHONY: deploy-ui-remote
deploy-ui-remote:
	fly deploy --config $(CONFIG_UI) --app $(APP_NAME_UI) --remote-only

# --- Secrets -------------------------------------------------------
.PHONY: secrets-api
secrets-api: .env
	@echo "🔐 Pushing .env -> secrets on $(APP_NAME_API) (skip comments/blank)…"
	while IFS='=' read -r key val; do \
	  [[ $$key =~ ^#.*$$ || -z $$key ]] && continue; \
	  fly secrets set "$$key=$$val" -a $(APP_NAME_API) || exit 1; \
	done < .env

.PHONY: secrets-ui
secrets-ui: .env.ui
	@if [ -f .env.ui ]; then \
	  echo "🔐 Pushing .env.ui -> secrets on $(APP_NAME_UI)…"; \
	  while IFS='=' read -r key val; do \
	    [[ $$key =~ ^#.*$$ || -z $$key ]] && continue; \
	    fly secrets set "$$key=$$val" -a $(APP_NAME_UI) || exit 1; \
	  done < .env.ui; \
	else \
	  echo "ℹ️  .env.ui not found; skipping UI secrets."; \
	fi

# --- Logs / Status / SSH / Scale ---------------------------------
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

.PHONY: ssh-api
ssh-api:
	@MID=$$(fly machines list -a $(APP_NAME_API) --json | jq -r '.[0].id'); \
	[ -n "$$MID" ] || { echo "❌ no machines for $(APP_NAME_API)"; exit 1; }; \
	echo "🔌 SSH -> $$MID"; \
	fly ssh console -a $(APP_NAME_API) -s $$MID

.PHONY: ssh-ui
ssh-ui:
	@MID=$$(fly machines list -a $(APP_NAME_UI) --json | jq -r '.[0].id'); \
	[ -n "$$MID" ] || { echo "❌ no machines for $(APP_NAME_UI)"; exit 1; }; \
	echo "🔌 SSH -> $$MID"; \
	fly ssh console -a $(APP_NAME_UI) -s $$MID

.PHONY: scale-api
scale-api:
	@count=$${N:-1}; \
	echo "📈 Scaling $(APP_NAME_API) -> $$count"; \
	fly scale count $$count -a $(APP_NAME_API)

.PHONY: scale-ui
scale-ui:
	@count=$${N:-1}; \
	echo "📈 Scaling $(APP_NAME_UI) -> $$count"; \
	fly scale count $$count -a $(APP_NAME_UI)

# --- Open / Health / Doctor --------------------------------------
.PHONY: open-api
open-api:
	$(OPEN_CMD) "https://$(APP_NAME_API).fly.dev/health" >/dev/null 2>&1 || true
	@echo "🌐 Opened https://$(APP_NAME_API).fly.dev/health"

.PHONY: health-api
health-api:
	@code=$$($(CURL_OK) "https://$(APP_NAME_API).fly.dev/health"); \
	echo "API /health -> $$code"; \
	test "$$code" = "200"

.PHONY: health-ui
health-ui:
	@code=$$($(CURL_OK) "https://$(APP_NAME_UI).fly.dev/"); \
	echo "UI / -> $$code"; \
	test "$$code" = "200"

.PHONY: doctor-api
doctor-api:
	@echo "🔬 Machines:"; fly machines list -a $(APP_NAME_API) || true
	@echo "🔬 Last 120 log lines:"; fly logs -a $(APP_NAME_API) -n 120 || true
	@echo "🔬 Public health:"; $(MAKE) -s health-api || true

# Run a private mesh health check from INSIDE the UI machine
.PHONY: doctor-internal
doctor-internal:
	@echo "🔎 From $(APP_NAME_UI) → http://$(INTERNAL_HOST):$(INTERNAL_PORT)/health"
	fly ssh console -a $(APP_NAME_UI) -C "getent hosts $(INTERNAL_HOST) && curl -g -sSf http://$(INTERNAL_HOST):$(INTERNAL_PORT)/health || echo '❌ internal curl failed'"

# --- BACKEND_URL toggles for UI -----------------------------------
# Writes BACKEND_URL into UI app env as a Fly secret (Apps V2 best practice)
.PHONY: set-ui-backend-private
set-ui-backend-private:
	fly secrets set BACKEND_URL="http://$(INTERNAL_HOST):$(INTERNAL_PORT)" -a $(APP_NAME_UI)
	@echo "✅ UI BACKEND_URL set to private mesh: http://$(INTERNAL_HOST):$(INTERNAL_PORT)"

.PHONY: set-ui-backend-public
set-ui-backend-public:
	fly secrets set BACKEND_URL="https://$(APP_NAME_API).fly.dev" -a $(APP_NAME_UI)
	@echo "✅ UI BACKEND_URL set to public: https://$(APP_NAME_API).fly.dev"

# --- Nuke (fresh machine) -----------------------------------------
.PHONY: nuke-api
nuke-api:
	@echo "💣 Cycling $(APP_NAME_API) machines (0 → 1)…"
	fly scale count 0 -a $(APP_NAME_API)
	sleep 2
	fly scale count 1 -a $(APP_NAME_API)

.PHONY: nuke-ui
nuke-ui:
	@echo "💣 Cycling $(APP_NAME_UI) machines (0 → 1)…"
	fly scale count 0 -a $(APP_NAME_UI)
	sleep 2
	fly scale count 1 -a $(APP_NAME_UI)