# Trifivend API – Fly Machines friendly build
FROM python:3.11-slim

WORKDIR /app

# Install backend deps (make sure uvicorn is in this file)
COPY requirements.backend.txt /app/
RUN pip install --no-cache-dir -r requirements.backend.txt

# App source
COPY . /app

# Network + runtime
ENV PORT=8080
EXPOSE 8080

# Ensure entrypoint is executable
RUN chmod +x /app/docker-entrypoint.sh

# Correct JSON-array CMD (no shell parsing issues)
CMD ["/app/docker-entrypoint.sh"]
