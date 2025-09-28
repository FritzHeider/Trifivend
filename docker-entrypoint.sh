#!/bin/sh
set -e

if [ "$#" -gt 0 ]; then
  if [ "$#" -eq 1 ]; then
    exec sh -c "$1"
  else
    exec "$@"
  fi
fi

PORT="${PORT:-8080}"
exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
