# Use slim base Python image
FROM python:3.10-slim

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg libasound2 && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install pip dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Set environment variables (override with Fly secrets)
ENV PYTHONUNBUFFERED=1 \
    PORT=8080

# Expose port
EXPOSE 8080

# Run app with Uvicorn
CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8080"]