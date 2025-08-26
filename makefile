# ---- Config ----
APP_NAME := ai-vendbot
FLY_URL  := https://$(APP_NAME).fly.dev
LOCAL_PORT := 8080

# ---- Python env (local) ----
.PHONY: venv
venv:
	python3 -m venv .venv && . .venv/bin/activate && pip install -U pip

.PHONY: deps-backend
deps-backend: venv
	. .venv/bin/activate && pip install -r requirements.backend.txt

.PHONY: deps-ui
deps-ui: venv
	. .venv/bin/activate && pip install -r requirements.ui.txt

# ---- Run locally ----
.PHONY: run-backend
run-backend: deps-backend
	. .venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port $(LOCAL_PORT)

.PHONY: run-ui
run-ui: deps-ui
	cd ui && . ../.venv/bin/activate && streamlit run streamlit_app.py

# ---- Fly.io ----
.PHONY: deploy
deploy:
	fly deploy --remote-only

.PHONY: secrets
secrets:
	@test "$(TWILIO_ACCOUNT_SID)" != "" || (echo "TWILIO_ACCOUNT_SID missing"; exit 1)
	@test "$(TWILIO_AUTH_TOKEN)"  != "" || (echo "TWILIO_AUTH_TOKEN missing"; exit 1)
	@test "$(TWILIO_NUMBER)"      != "" || (echo "TWILIO_NUMBER missing"; exit 1)
	fly secrets set \
	  TWILIO_ACCOUNT_SID=$(TWILIO_ACCOUNT_SID) \
	  TWILIO_AUTH_TOKEN=$(TWILIO_AUTH_TOKEN) \
	  TWILIO_NUMBER=$(TWILIO_NUMBER) \
	  APP_BASE_URL=$(FLY_URL)

.PHONY: logs
logs:
	fly logs

# ---- Smoke tests ----
.PHONY: health
health:
	curl -sS "$(FLY_URL)/health" | python -m json.tool

.PHONY: call
call:
	@test "$(TO)" != "" || (echo 'Usage: make call TO=+1XXXXXXXXXX NAME="Riley"'; exit 1)
	curl -sS -X POST "$(FLY_URL)/call" \
	  -H 'content-type: application/json' \
	  -d '{"to":"$(TO)","lead_name":"$(NAME)","property_type":"apartment","location_area":"San Francisco","callback_offer":"schedule a free design session"}' \
	  | python -m json.tool