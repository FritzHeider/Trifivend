#!/bin/sh
set -e

# If Fly passed a command (via [processes] or docker run CMD), run that.
# Handle both: a single string or tokenized args.
if [ "$#" -gt 0 ]; then
  # Recompose args into a single shell line to support Fly's single-string form
  # as well as tokenized forms.
  exec sh -lc "$*"
fi

# Default to serving the FastAPI app if no command was provided.
: "${PORT:=8080}"
: "${HOST:=0.0.0.0}"
: "${APP_MODULE:=main:app}"

# Sanity echo (shows up once in logs)
echo "Starting uvicorn ${APP_MODULE} on ${HOST}:${PORT}"
exec uvicorn "${APP_MODULE}" --host "${HOST}" --port "${PORT}"