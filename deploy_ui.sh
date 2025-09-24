#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME_UI:-trifivend-ui}"
PRIMARY_REGION="${PRIMARY_REGION:-sjc}"
TOML="${TOML_UI:-fly.ui.toml}"

echo "🎨 Deploying UI → $APP_NAME ($TOML)"

[[ -f .env ]] || { echo "❌ Missing .env (copy .env.example)"; exit 1; }
set -a; source .env; set +a

if ! fly apps list | grep -q "^$APP_NAME\b"; then
  echo "🛠 Creating Fly app: $APP_NAME"
  fly apps create "$APP_NAME" 
fi

# Prefer private networking to avoid CORS:
BACKEND_URL="${UI_BACKEND_URL:-http://ai-vendbot.internal:8080}"

echo "🔐 Setting UI secrets..."
fly secrets set \
  BACKEND_URL="$BACKEND_URL" \
  SUPABASE_URL="${SUPABASE_URL:-}" \
  SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-}" \
  -a "$APP_NAME"

echo "📦 Deploying UI..."
fly deploy -c "$TOML" -a "$APP_NAME"

echo "✅ UI deployed: https://$APP_NAME.fly.dev"
