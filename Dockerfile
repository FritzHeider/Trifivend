# Dockerfile — TriFiVend (backend + UI)
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080


# --- deps ---
WORKDIR /app
COPY requirements.backend.txt /tmp/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r /tmp/requirements.txt

# copy the app
COPY . /app

# expose + start
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "::", "--port", "8080"]