# Certificate Manager Dockerfile for Python libp2p WebSocket Transport
# Based on patterns from js-libp2p and go-libp2p implementations

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    openssl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy certificate manager code
COPY examples/production_deployment/cert_manager.py .
COPY libp2p/transport/websocket/autotls.py ./autotls.py

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir cryptography trio

# Create non-root user
RUN groupadd -r certmanager && useradd -r -g certmanager certmanager

# Create directories
RUN mkdir -p /app/certs /app/logs && \
    chown -R certmanager:certmanager /app

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV CERT_STORAGE_PATH=/app/certs
ENV RENEWAL_THRESHOLD_HOURS=24

# Switch to non-root user
USER certmanager

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os; exit(0 if os.path.exists('/app/certs') else 1)"

# Default command
CMD ["python", "cert_manager.py"]
