#!/usr/bin/env zsh
set -euo pipefail

./deploy_api.sh
./deploy_ui.sh || true