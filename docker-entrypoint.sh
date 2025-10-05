#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-8080}"

if [[ -n "${LOG_LEVEL:-}" ]]; then
  export LOG_LEVEL_UPPER="$(echo "$LOG_LEVEL" | tr '[:lower:]' '[:upper:]')"
else
  export LOG_LEVEL_UPPER="INFO"
fi

echo "[entrypoint] Starting: $* on 0.0.0.0:${PORT} (LOG_LEVEL=${LOG_LEVEL_UPPER})"
exec "$@"