#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME_API:-ai-callbot}"
PRIMARY_REGION="${PRIMARY_REGION:-sjc}"
TOML="${TOML_API:-fly.api.toml}"

echo "🚀 Deploying API → $APP_NAME ($TOML)"

[[ -f .env ]] || { echo "❌ Missing .env (copy .env.example)"; exit 1; }
set -a; source .env; set +a

if ! fly apps list | grep -q "^$APP_NAME\b"; then
  echo "🛠 Creating Fly app: $APP_NAME"
  fly apps create "$APP_NAME" 
fi

echo "🔐 Setting API secrets..."
fly secrets set \
  OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
  SUPABASE_URL="${SUPABASE_URL:-}" \
  SUPABASE_SERVICE_KEY="${SUPABASE_SERVICE_KEY:-}" \
  ELEVEN_API_KEY="${ELEVEN_API_KEY:-}" \
  TWILIO_ACCOUNT_SID="${TWILIO_ACCOUNT_SID:-}" \
  TWILIO_AUTH_TOKEN="${TWILIO_AUTH_TOKEN:-}" \
  TWILIO_NUMBER="${TWILIO_NUMBER:-}" \
  VOICE_WEBHOOK_URL="${VOICE_WEBHOOK_URL:-}" \
  LEAD_PHONE="${LEAD_PHONE:-}" \
  -a "$APP_NAME"

echo "📦 Deploying API..."
fly deploy -c "$TOML" -a "$APP_NAME"

echo "✅ API deployed: https://$APP_NAME.fly.dev  (private: $APP_NAME.internal:8080)"
