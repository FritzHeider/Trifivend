FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y curl \
 && rm -rf /var/lib/apt/lists/*

# Install only backend deps
COPY requirements.backend.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install -r requirements.txt

# Copy app code last
COPY . .

ENV PORT=8080
EXPOSE 8080
# Launch via Python module to avoid PATH issues
CMD ["python","-m","uvicorn","main:app","--host","0.0.0.0","--port","8080"]