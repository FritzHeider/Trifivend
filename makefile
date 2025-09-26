# Makefile — two-app Fly.io workflow
APP_NAME_API ?= ai-callbot
APP_NAME_UI  ?= trifivend-ui
PRIMARY_REGION ?= sjc

TOML_API ?= fly.api.toml
TOML_UI  ?= fly.ui.toml

.PHONY: help
help:
	@echo "Targets:"
	@echo "  deploy-api       Deploy the FastAPI app ($(APP_NAME_API))"
	@echo "  deploy-ui        Deploy the Streamlit UI ($(APP_NAME_UI))"
	@echo "  deploy-both      Deploy API then UI"
	@echo "  secrets-api      Push API secrets from .env"
	@echo "  secrets-ui       Push UI secrets from .env"
	@echo "  logs-api         Tail API logs"
	@echo "  logs-ui          Tail UI logs"
	@echo "  status-api       Fly status for API"
	@echo "  status-ui        Fly status for UI"

# ===== Secrets =====
.PHONY: secrets-api
secrets-api:
	@test -f .env || (echo "Missing .env — copy .env.example and fill"; exit 1)
	set -a; . ./.env; set +a; \
	fly secrets set \
		OPENAI_API_KEY="$$OPENAI_API_KEY" \
		SUPABASE_URL="$$SUPABASE_URL" \
		SUPABASE_SERVICE_KEY="$$SUPABASE_SERVICE_KEY" \
		ELEVEN_API_KEY="$$ELEVEN_API_KEY" \
		TWILIO_ACCOUNT_SID="$$TWILIO_ACCOUNT_SID" \
		TWILIO_AUTH_TOKEN="$$TWILIO_AUTH_TOKEN" \
		TWILIO_NUMBER="$$TWILIO_NUMBER" \
		VOICE_WEBHOOK_URL="$$VOICE_WEBHOOK_URL" \
		LEAD_PHONE="$$LEAD_PHONE" \
		-a $(APP_NAME_API)

.PHONY: secrets-ui
secrets-ui:
	@test -f .env || (echo "Missing .env — copy .env.example and fill"; exit 1)
	set -a; . ./.env; set +a; \
	fly secrets set \
		BACKEND_URL="$${UI_BACKEND_URL:-http://$(APP_NAME_API).internal:8080}" \
		SUPABASE_URL="$$SUPABASE_URL" \
		SUPABASE_ANON_KEY="$$SUPABASE_ANON_KEY" \
		-a $(APP_NAME_UI)

# ===== Deploys =====
.PHONY: deploy-api
deploy-api:
	@fly apps list | grep -q "^$(APP_NAME_API)\b" || fly apps create "$(APP_NAME_API)" --region "$(PRIMARY_REGION)"
	fly deploy -c $(TOML_API) -a $(APP_NAME_API)

.PHONY: deploy-ui
deploy-ui:
	@fly apps list | grep -q "^$(APP_NAME_UI)\b" || fly apps create "$(APP_NAME_UI)" --region "$(PRIMARY_REGION)"
	fly deploy -c $(TOML_UI) -a $(APP_NAME_UI)

.PHONY: deploy-both
deploy-both: deploy-api deploy-ui
	@echo "Deployed: API=https://$(APP_NAME_API).fly.dev  UI=https://$(APP_NAME_UI).fly.dev"

# ===== Ops =====
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
