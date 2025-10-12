#!/bin/sh
set -eu
# Single IPv6 bind; works with Fly's fdaa::/64 mesh and public edge.
exec gunicorn main:app \
  -k uvicorn.workers.UvicornWorker \
  -b [::]:${PORT:-8080} \
  --log-level info
