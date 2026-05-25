# ── Stage: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL maintainer="DDoS-Sim Project"
LABEL description="Target Web Application – Phase 1 (No Defense)"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Working directory inside container
WORKDIR /app

# Install Python dependencies first (layer caching optimization)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app.py .

# Expose Flask default port
EXPOSE 5000

# Health check (Docker will mark container as unhealthy if this fails)
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Run with Gunicorn: 4 worker processes for realistic load testing
# Workers = (2 × CPU cores) + 1  →  2 workers is safe for a VM with 1 core
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "2", \
     "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
