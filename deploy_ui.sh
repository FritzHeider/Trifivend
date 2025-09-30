#!/usr/bin/env zsh
set -euo pipefail

APP_NAME="ai-callbot-ui"
CONFIG="fly.ui.toml"

echo "🚀 Deploying $APP_NAME using $CONFIG..."
fly deploy --config "$CONFIG" --app "$APP_NAME"

echo "🔎 Status:"
fly status -a "$APP_NAME"