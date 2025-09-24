# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates git \
  && rm -rf /var/lib/apt/lists/*

# Copy ONLY the files that exist
COPY requirements.backend.txt /tmp/requirements.backend.txt
COPY requirements.ui.txt      /tmp/requirements.ui.txt

# You MUST pass REQS via build args (fly.toml does this)
ARG REQS
RUN test -n "$REQS" || (echo "Set build arg REQS to one of /tmp/requirements.backend.txt or /tmp/requirements.ui.txt" && exit 1)
RUN python -m pip install --upgrade pip && python -m pip install -r "$REQS"

# App source
COPY . /app

# ... previous Dockerfile content ...
ENV PYTHONPATH=/app

# Streamlit envs are harmless for API images
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501

# 👇 Run whatever START_CMD is set to at runtime
CMD ["bash","-lc","${START_CMD}"]