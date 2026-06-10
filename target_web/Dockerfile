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

# Run with Gunicorn: 4 workers × 4 threads để Phase 2 attack thấy rõ tác dụng
# 2 workers × 2 threads quá ít → 150 attack workers sẽ bị CONN_ERR ngay
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "4", \
     "--worker-connections", "200", "--timeout", "30", \
     "--access-logfile", "-", "--error-logfile", "-", "app:app"]
