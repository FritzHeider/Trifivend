# Trifivend ops helpers (Fly Machines + internal mesh)

.PHONY: doctor-internal doctor-api deploy-api deploy-ui set-ui-backend-private logs-api logs-api-machine

# Validate UI → API internal mesh DNS and health
doctor-internal:
	@echo "🔎 trifivend-ui → http://ai-callbot.internal:8080/health"
	fly ssh console -a trifivend-ui -C "bash -lc 'curl -sSf http://ai-callbot.internal:8080/health && echo && echo ✅ OK || echo ❌ FAILED'"

# Show Machines, recent logs, and public health for API
doctor-api:
	@echo "🔬 Machines:"
	fly machines list -a ai-callbot
	@echo "\n🔬 Recent logs (no tail):"
	fly logs -a ai-callbot --no-tail
	@echo "\n🔬 Health (public):"
	@code=$$(curl -s -o /dev/null -w "%{http_code}" https://ai-callbot.fly.dev/health); \
	if [ "$$code" = "200" ]; then echo "API /health → 200 ✅"; else echo "API /health → $$code ❌"; exit 1; fi

# App-wide logs helper
logs-api:
	fly logs -a ai-callbot --no-tail

# Per-machine logs: make logs-api-machine M=<machine_id>
logs-api-machine:
	@if [ -z "$$M" ]; then echo "Usage: make logs-api-machine M=<machine_id>"; exit 1; fi
	fly logs -a ai-callbot --machine "$$M" --no-tail

# Deploys (remote builder so you don't need local Docker)


deploy-ui:
	fly deploy -a trifivend-ui --remote-only --now

# Point UI at API over Fly's internal mesh DNS
set-ui-backend-private:
	fly secrets set BACKEND_URL=http://ai-callbot.internal:8080 -a trifivend-ui
	@echo "✅ BACKEND_URL → internal mesh"
deploy-api:
	fly deploy --config fly.api.toml --local-only
	./post_deploy_guard.sh
