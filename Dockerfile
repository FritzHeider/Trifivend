# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    HOST=0.0.0.0 \
    APP_MODULE=main:app

WORKDIR /app

# Minimal system deps
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

# Requirements (both files available; pick via REQS if you reuse the image for UI)
COPY requirements.backend.txt /tmp/requirements.backend.txt
COPY requirements.ui.txt      /tmp/requirements.ui.txt
ARG REQS=/tmp/requirements.backend.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -r "$REQS"

# App source
COPY . /app
ENV PYTHONPATH=/app

# Lightweight entrypoint that respects Fly's [processes] command
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

# Important: keep ENTRYPOINT; let it exec either Fly's command or default API
ENTRYPOINT ["/entrypoint.sh"]
CMD []