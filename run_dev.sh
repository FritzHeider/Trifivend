#!/usr/bin/env bash

# Move to script's directory
cd "$(dirname "$0")"

# Set PYTHONPATH to project root
export PYTHONPATH="$(pwd)"

# Run FastAPI with live reload
echo "Launching dev server from: $(pwd)"
uvicorn app.backend.main:app --reload