# Backend Dockerfile for AI Math Tutor
FROM python:3.11-slim

# Set environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies (including curl for healthcheck)
# libpq-dev is needed for building psycopg2 if binary wheel fails (though binary is used)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies via pip (simpler than poetry in CI/Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Health check using curl (updated to use PORT)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Run the application (listens on Cloud Run's $PORT, defaults to 8080)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
