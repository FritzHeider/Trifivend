#!/bin/bash

set -e  # Exit on any error

# === CONFIG ===
APP_NAME="ai-vendbot"
PRIMARY_REGION="sjc"

echo "🚀 Deploying $APP_NAME to Fly.io..."

# 1. Check for .env file
if [ ! -f ".env" ]; then
  echo "❌ .env file missing. Please create one with your secrets."
  exit 1
fi

# 2. Load .env file variables
echo "🔐 Loading secrets from .env..."
set -o allexport
source .env
set +o allexport

# 3. Create Fly app if it doesn't exist
if ! fly apps list | grep -q "$APP_NAME"; then
  echo "🛠 Creating Fly app: $APP_NAME"
  fly apps create "$APP_NAME" --region "$PRIMARY_REGION"
fi

# 4. Create or validate fly.toml
if [ ! -f "fly.toml" ]; then
  echo "📝 Creating fly.toml"
  echo "app = \"$APP_NAME\"" > fly.toml
  echo "primary_region = \"$PRIMARY_REGION\"" >> fly.toml
fi

# 5. Set secrets on Fly
echo "🔐 Setting Fly secrets..."
fly secrets set \
  SUPABASE_URL="$SUPABASE_URL" \
  SUPABASE_SERVICE_KEY="$SUPABASE_SERVICE_KEY" \
  ELEVEN_API_KEY="$ELEVEN_API_KEY" \
  OPENAI_API_KEY="$OPENAI_API_KEY" \
  TWILIO_SID="$TWILIO_SID" \
  TWILIO_AUTH_TOKEN="$TWILIO_AUTH_TOKEN" \
  TWILIO_NUMBER="$TWILIO_NUMBER" \
  LEAD_PHONE="$LEAD_PHONE" \
  VOICE_WEBHOOK_URL="$VOICE_WEBHOOK_URL" \
  -a "$APP_NAME"

# 6. Deploy the app
echo "📦 Deploying to Fly.io..."
fly deploy -a "$APP_NAME"

# 7. Done
echo "✅ Deployed! Your app is live at: https://$APP_NAME.fly.dev"
