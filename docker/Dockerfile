# AI_FREELANCE_AUTOMATION - Production Dockerfile
# Multi-stage build for minimal, secure, and efficient image

# ==============================
# STAGE 1: Build dependencies (with optional GPU support)
# ==============================
ARG PYTHON_VERSION=3.11
ARG USE_GPU=false

# Choose base image based on GPU requirement
FROM python:${PYTHON_VERSION}-slim AS base

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        gcc \
        g++ \
        libpq-dev \
        && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create non-root user
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid 1001 --shell /bin/bash --create-home appuser

# Copy dependency files
COPY requirements.txt requirements-prod.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    if [ "$USE_GPU" = "true" ]; then \
        pip install --no-cache-dir -r requirements-gpu.txt; \
    else \
        pip install --no-cache-dir -r requirements-prod.txt; \
    fi

# ==============================
# STAGE 2: Final production image
# ==============================
FROM base AS production

# Copy application code
COPY . .

# Set ownership to non-root user
RUN chown -R appuser:appuser /app
USER appuser

# Expose ports
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Default command
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]