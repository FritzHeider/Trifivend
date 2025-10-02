# Dockerfile — ai-callbot (FastAPI + Uvicorn)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    UVICORN_PORT=8080 \
    UVICORN_HOST=0.0.0.0

WORKDIR /app

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl bash && \
    rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install the full dependency set
COPY requirements.backend.txt ./requirements.backend.txt

RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.backend.txt

# Copy app
# If your module is in /app (i.e., main.py at project root), copy everything;
# otherwise adjust to COPY app ./app and start uvicorn app.main:app
COPY . .

# Entry
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

# NOTE: main:app expects "main.py" in the workdir providing "app = FastAPI()"
CMD ["/entrypoint.sh", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
