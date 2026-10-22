FROM python:3.13-slim

WORKDIR /app

# Prefer system CA bundle while base images may still ship vulnerable pip
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# Install only the toolchain needed to build/install py-libp2p.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    build-essential \
    cmake \
    pkg-config \
    libgmp-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /var/cache/apt/*.bin

# Install pinned patched uv via Astral installer (avoid unpinned pip install uv
# on images that may still ship vulnerable pip after eMudhra/emSign CA incident)
RUN curl -LsSf https://astral.sh/uv/0.13.5/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && uv --version

# Build context = repo root (same as interop/transport/Dockerfile for GitHub + local)
COPY . /app/py-libp2p

RUN uv venv /app/venv

# Interop/perf project: depends on libp2p from copied clone
COPY interop/perf/pyproject.toml .
RUN uv pip install --python /app/venv/bin/python "pip>=26.2.2" && \
    uv pip install --python /app/venv/bin/python --no-cache-dir -e .

COPY interop/perf/perf_test.py .

ENV PYTHONUNBUFFERED=1
ENV CI=true
ENV PATH="/app/venv/bin:${PATH}"

ENTRYPOINT ["/app/venv/bin/python", "perf_test.py"]
