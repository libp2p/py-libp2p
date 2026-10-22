FROM python:3.13-slim

WORKDIR /app

# Prefer system CA bundle while base images may still ship vulnerable pip
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# Install system dependencies (includes libsrtp2-dev for aiortc/WebRTC)
RUN apt-get update && apt-get install -y \
    ca-certificates \
    redis-tools \
    build-essential \
    cmake \
    pkg-config \
    libgmp-dev \
    libsrtp2-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pinned patched uv via Astral installer (avoid unpinned pip install uv
# on images that may still ship vulnerable pip after eMudhra/emSign CA incident)
RUN curl -LsSf https://astral.sh/uv/0.13.5/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && uv --version

# Copy the py-libp2p-${commitSha} folder so we can use it as a local dependency
COPY ./ /app/py-libp2p

# Create virtual environment using uv (as per contributing.rst)
RUN uv venv /app/venv

# Copy pyproject.toml and install Python dependencies using uv
# Use the venv's Python explicitly with uv pip
COPY interop/transport/pyproject.toml .
RUN uv pip install --python /app/venv/bin/python "pip>=26.2.2" && \
    uv pip install --python /app/venv/bin/python --no-cache-dir -e .

# Copy the ping test implementation
COPY interop/transport/ping_test.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CI=true
ENV PATH="/app/venv/bin:${PATH}"

# Set the entrypoint to run the ping test using venv Python
ENTRYPOINT ["/app/venv/bin/python", "ping_test.py"]
