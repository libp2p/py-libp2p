FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    redis-tools \
    build-essential \
    cmake \
    pkg-config \
    libgmp-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (using pip method, also mentioned in contributing.rst)
# This ensures uv is in a standard location (Python's bin directory)
RUN pip install --no-cache-dir uv

# Verify uv installation
RUN uv --version

# Copy the py-libp2p-${commitSha} folder so we can use it as a local dependency
COPY ./ /app/py-libp2p

# Create virtual environment using uv (as per contributing.rst)
RUN uv venv /app/venv

# Copy pyproject.toml and install Python dependencies using uv
# Use the venv's Python explicitly with uv pip
COPY interop/transport/pyproject.toml .
RUN uv pip install --python /app/venv/bin/python --upgrade pip && \
    uv pip install --python /app/venv/bin/python --no-cache-dir -e .

# Copy the ping test implementation
COPY interop/transport/ping_test.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CI=true
ENV PATH="/app/venv/bin:${PATH}"

# Set the entrypoint to run the ping test using venv Python
ENTRYPOINT ["/app/venv/bin/python", "ping_test.py"]
