# Root Dockerfile for Cloud Run deployment
# Cloud Build uses the repo root as context, so we build from backend/
FROM python:3.11-slim

# Set environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies (including curl for healthcheck and Kaleido for PNG export)
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

# Install Python dependencies from backend/
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the backend application code
COPY backend/ .

# Expose port (Cloud Run uses $PORT, default 8080)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Run the application (listens on Cloud Run's $PORT, defaults to 8080)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
