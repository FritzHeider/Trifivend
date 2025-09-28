#!/bin/sh
set -e

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

PORT="${PORT:-8080}"
exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
