
#!/bin/bash

set -e  # Exit on any error

# === CONFIG ===
APP_NAME="ai-vendbot"
PRIMARY_REGION="sjc"

echo "🚀 Deploying $APP_NAME to Fly.io..."

# 1. Clean old .fly config if exists
if [ -d ".fly" ]; then
  echo "🧹 Removing stale .fly config..."
  rm -rf .fly
fi

# 2. Launch app config if it hasn't been initialized
fly launch --app "$APP_NAME" --region "$PRIMARY_REGION" --no-deploy --copy-config

# 3. Load secrets from .env file (secure, not committed to Git)
if [ ! -f ".env" ]; then
  echo "❌ .env file missing. Please create one with your secrets."
  exit 1
fi

echo "🔐 Setting secrets from .env..."
set -o allexport
source .env
set +o allexport

fly secrets set \
  SUPABASE_URL="$SUPABASE_URL" \
  SUPABASE_KEY="$SUPABASE_KEY" \
  ELEVEN_API_KEY="$ELEVEN_API_KEY" \
  OPENAI_API_KEY="$OPENAI_API_KEY" \
  TWILIO_SID="$TWILIO_SID" \
  TWILIO_AUTH_TOKEN="$TWILIO_AUTH_TOKEN" \
  TWILIO_NUMBER="$TWILIO_NUMBER" \
  LEAD_PHONE="$LEAD_PHONE" \
  VOICE_WEBHOOK_URL="$VOICE_WEBHOOK_URL" \
  --app "$APP_NAME"

# 4. Deploy
echo "📦 Deploying app to Fly.io..."
fly deploy --app "$APP_NAME"

# 5. Show URL
echo "✅ Deployed! Visit: https://$APP_NAME.fly.dev"