#!/usr/bin/env zsh
set -euo pipefail

APP_NAME="ai-callbot"
CONFIG="fly.api.toml"

echo "🔐 Syncing secrets from .env to $APP_NAME..."
while IFS='=' read -r key val; do
  [[ $key =~ ^#.*$ || -z $key ]] && continue
  fly secrets set "$key=$val" -a "$APP_NAME"
done < .env

echo "🚀 Deploying $APP_NAME using $CONFIG..."
fly deploy --config "$CONFIG" --app "$APP_NAME"

echo "🔎 Status:"
fly status -a "$APP_NAME"
echo "🌐 Health:"
curl -sf "https://$APP_NAME.fly.dev/health" && echo