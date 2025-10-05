# Use a slim base image
FROM python:3.13-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=8080

# Install dependencies
WORKDIR /app
COPY pyproject.toml poetry.lock* /app/
RUN pip install --upgrade pip \
    && pip install poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-dev

# Copy source
COPY . /app

# Exposure
EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "::", "--port", "8080"]