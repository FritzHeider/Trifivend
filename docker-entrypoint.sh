#!/bin/sh
set -eu
exec gunicorn main:app \
  -k uvicorn.workers.UvicornWorker \
  -b 0.0.0.0:${PORT:-8080} \
  -b [::]:${PORT:-8080} \
  --log-level info
