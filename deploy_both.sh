#!/usr/bin/env bash
set -euo pipefail

export APP_NAME_API="${APP_NAME_API:-ai-callbot}"
export APP_NAME_UI="${APP_NAME_UI:-trifivend-ui}"
export TOML_API="${TOML_API:-fly.api.toml}"
export TOML_UI="${TOML_UI:-fly.ui.toml}"
export PRIMARY_REGION="${PRIMARY_REGION:-sjc}"

./deploy_api.sh
./deploy_ui.sh

echo "🥂 Done. UI → https://$APP_NAME_UI.fly.dev | API → https://$APP_NAME_API.fly.dev"
echo "🔒 Private UI→API: http://$APP_NAME_API.internal:8080"
