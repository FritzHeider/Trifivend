#!/usr/bin/env bash
set -euo pipefail

# Ensure PORT is honored (Fly sets $PORT)
export PORT="${PORT:-8080}"

# Basic logging level normalization for child processes if you pass LOG_LEVEL=info
if [[ -n "${LOG_LEVEL:-}" ]]; then
  export LOG_LEVEL_UPPER="$(echo "$LOG_LEVEL" | tr '[:lower:]' '[:upper:]')"
else
  export LOG_LEVEL_UPPER="INFO"
fi

echo "[entrypoint] Starting: $* on 0.0.0.0:${PORT} (LOG_LEVEL=${LOG_LEVEL_UPPER})"
exec "$@"