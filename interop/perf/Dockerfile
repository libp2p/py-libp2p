FROM python:3.13-slim

ARG UV_VERSION=0.5.31

WORKDIR /app

# Install only required build/runtime dependencies for local libp2p install.
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    libgmp-dev \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv (docs/contributing.rst Option 2: same as CI)
RUN pip install --no-cache-dir "uv==${UV_VERSION}"
RUN uv --version

# Build context = repo root (same as interop/transport/Dockerfile for GitHub + local)
COPY . /app/py-libp2p

RUN uv venv /app/venv

# Interop/perf project: depends on libp2p from copied clone
COPY interop/perf/pyproject.toml .
COPY interop/perf/perf_test.py .
RUN uv pip install --python /app/venv/bin/python --upgrade pip && \
    uv pip install --python /app/venv/bin/python --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ENV CI=true
ENV HTTP_PROXY=
ENV HTTPS_PROXY=
ENV ALL_PROXY=
ENV NO_PROXY=*
ENV PATH="/app/venv/bin:${PATH}"

ENTRYPOINT ["/app/venv/bin/python", "perf_test.py"]
