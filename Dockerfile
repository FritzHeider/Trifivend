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

# Copy a lightweight entrypoint that defaults to serving the API. The script
# respects any explicit command provided by Fly's [processes] config, making
# the same image usable for both the API and UI deployments.
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose for clarity (Fly uses internal_port anyway)
EXPOSE 8080

# Default to running the FastAPI app. When Fly's [processes] provides a command
# (e.g. the Streamlit UI), the entrypoint simply execs that command instead.
ENTRYPOINT ["/entrypoint.sh"]
CMD []

