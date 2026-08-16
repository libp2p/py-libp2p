FROM python:3.13-slim

WORKDIR /app

# Install only the toolchain needed to build/install py-libp2p.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    libgmp-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /var/cache/apt/*.bin

# Install uv (docs/contributing.rst Option 2: same as CI)
RUN pip install --no-cache-dir uv
RUN uv --version

# Build context = repo root (same as interop/transport/Dockerfile for GitHub + local)
COPY . /app/py-libp2p

RUN uv venv /app/venv

# Interop/perf project: depends on libp2p from copied clone
COPY interop/perf/pyproject.toml .
RUN uv pip install --python /app/venv/bin/python --upgrade pip && \
    uv pip install --python /app/venv/bin/python --no-cache-dir -e .

COPY interop/perf/perf_test.py .

ENV PYTHONUNBUFFERED=1
ENV CI=true
ENV PATH="/app/venv/bin:${PATH}"

ENTRYPOINT ["/app/venv/bin/python", "perf_test.py"]
