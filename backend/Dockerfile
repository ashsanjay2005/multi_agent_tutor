# Backend Dockerfile for AI Math Tutor
FROM python:3.11-slim

# Set environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies (including curl for healthcheck and Kaleido for PNG export)
# libpq-dev is needed for building psycopg2 if binary wheel fails (though binary is used)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    libexpat1 \
    libfontconfig1 \
    libfreetype6 \
    libx11-6 \
    libxcb1 \
    libxext6 \
    libxrender1 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies via pip (simpler than poetry in CI/Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Health check using curl. This backend Dockerfile is used by docker-compose,
# which exposes container port 8000 by default.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Run the application
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
