# Dockerfile (monorepo: api + streamlit UI)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# base system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl bash build-essential && \
    rm -rf /var/lib/apt/lists/*

# ---- requirements selection (API by default) ----
# Copy both req files and pick via build arg
COPY requirements.backend.txt /tmp/requirements.backend.txt
COPY requirements.ui.txt      /tmp/requirements.ui.txt
ARG REQS=/tmp/requirements.backend.txt
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r ${REQS}

# ---- code ----
COPY . /app

# We keep CMD generic; Fly [processes] will override per app
# API default (harmless for UI because Fly will run "python -m streamlit ...")
ENV PORT=8080
EXPOSE 8080
# was:
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

# now:
CMD ["uvicorn", "main:app", "--host", "::", "--port", "8080"]