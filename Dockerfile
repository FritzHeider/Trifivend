# Use official slim Python image
FROM python:3.10-slim

# Set work directory
WORKDIR /app

# Install OS-level dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Set environment variable for port
ENV PORT=8080
EXPOSE 8080

# Start FastAPI app
CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8080"]