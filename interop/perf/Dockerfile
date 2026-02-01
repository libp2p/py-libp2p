FROM python:3.13-slim

WORKDIR /app

# Install system dependencies (contributing.rst + transport Dockerfile)
RUN apt-get update && apt-get install -y \
    redis-tools \
    build-essential \
    cmake \
    pkg-config \
    libgmp-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (docs/contributing.rst Option 2: same as CI)
RUN pip install --no-cache-dir uv
RUN uv --version

# Build context is perf/images/python/v0.x (path in images.yaml)
COPY py-libp2p /app/py-libp2p

RUN uv venv /app/venv

# Interop/perf project: depends on libp2p from copied clone
COPY py-libp2p/interop/perf/pyproject.toml .
RUN uv pip install --python /app/venv/bin/python --upgrade pip && \
    uv pip install --python /app/venv/bin/python --no-cache-dir -e .

COPY py-libp2p/interop/perf/perf_test.py .

ENV PYTHONUNBUFFERED=1
ENV CI=true
ENV PATH="/app/venv/bin:${PATH}"

ENTRYPOINT ["/app/venv/bin/python", "perf_test.py"]
