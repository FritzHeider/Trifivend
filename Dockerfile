# Dockerfile (API)
# Multi-stage build for small runtime image
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (ssl, libsndfile optional, curl for health/debug)
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements first for efficient caching
COPY requirements.backend.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . /app

# Security: non-root user
RUN useradd -m runner \
 && chown -R runner:runner /app
USER runner

# Expose internal port for Fly
ENV PORT=8080
EXPOSE 8080

# Healthcheck (optional, Fly also probes /health)
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT}/health || exit 1

# Run. Host '::' matches your code + dual-stack on Fly.
CMD ["python", "-m", "uvicorn", "main:app", "--host", "::", "--port", "8080", "--log-level", "info"]
