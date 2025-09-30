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

# Copy requirements if you have it; fall back to inline install
# If you use a requirements.txt, uncomment the next two lines:
# COPY requirements.txt .
# RUN pip install -r requirements.txt

# Install minimal runtime deps (FastAPI/uvicorn are required)
RUN python -m pip install --upgrade pip && \
    pip install \
      fastapi==0.115.0 \
      uvicorn[standard]==0.30.6 \
      python-dotenv==1.0.1 \
      sse-starlette==2.1.3 \
      pydantic==2.9.2 \
      pydantic-settings==2.5.2 \
      twilio==9.3.7

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