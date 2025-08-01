#!/usr/bin/env bash

set -e  # Exit immediately if any command fails

# Move to script's directory
cd "$(dirname "$0")"

# Set PYTHONPATH to project root
export PYTHONPATH="$(pwd)"

# Load .env line-by-line safely
if [ -f ".env" ]; then
  echo "🔐 Loading environment from .env"
  while IFS='=' read -r key value; do
    if [[ "$key" != "" && "$key" != \#* ]]; then
      export "$key=$value"
    fi
  done < .env
else
  echo "⚠️  No .env file found. Proceeding without local secrets."
fi

# Activate virtualenv if it exists
if [ -d "venv" ]; then
  source venv/bin/activate
  echo "🐍 Virtualenv activated."
fi

# Start FastAPI app using uvicorn, preserving PYTHONPATH for reload
echo "🚀 Launching dev server from: $(pwd)"
PYTHONPATH="$PYTHONPATH" uvicorn app.backend.main:app --reload --host 0.0.0.0 --port 8080
