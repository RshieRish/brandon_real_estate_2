FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Set unbuffered logging so prints show up in Railway Deploy logs
ENV PYTHONUNBUFFERED=1

# Expose port (using placeholder if PORT is not set)
EXPOSE ${PORT:-8000}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://0.0.0.0:${PORT:-8000}/health || exit 1

# Start command (using shell form so $PORT evaluates correctly)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
