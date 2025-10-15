APP_NAME ?= ai-callbot
PORT ?= 8080

.PHONY: help
help:
	@echo "Targets:"
	@echo "  install         Install backend deps"
	@echo "  dev             Run uvicorn reload on localhost:8080"
	@echo "  run             Run uvicorn on 0.0.0.0:8080"
	@echo "  fmt             Format with black + ruff --fix"
	@echo "  lint            Lint with ruff + black --check"
	@echo "  deploy-api      fly deploy (fly.api.toml)"
	@echo "  logs            fly logs -a $(APP_NAME)"

install:
	pip install -r requirements.backend.txt

dev:
	uvicorn main:app --reload --host 127.0.0.1 --port $(PORT)

run:
	uvicorn main:app --host 0.0.0.0 --port $(PORT)

fmt:
	black .
	ruff check . --fix

lint:
	ruff check .
	black --check .

deploy-api:
	fly deploy -c fly.api.toml --remote-only --strategy rolling

logs:
	fly logs -a $(APP_NAME)


supabase-start:
\tcd supabase && supabase start

supabase-stop:
\tcd supabase && supabase stop

supabase-reset:
\tcd supabase && supabase stop && rm -rf .branches .temp .volumes && supabase start
