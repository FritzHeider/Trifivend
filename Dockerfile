# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# System deps (keep minimal)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

# Provide both requirement files; pick one via build arg
COPY requirements.backend.txt /tmp/requirements.backend.txt
COPY requirements.ui.txt      /tmp/requirements.ui.txt

# Choose which set to install at build time
ARG REQS=/tmp/requirements.backend.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -r "$REQS"

# App source
COPY . /app
ENV PYTHONPATH=/app

# Expose for clarity (Fly uses internal_port anyway)
EXPOSE 8080

# Do NOT start the app here; Fly [processes] runs it (uvicorn via fly.api.toml)
# No CMD/ENTRYPOINT needed — keeps image reusable for API/UI