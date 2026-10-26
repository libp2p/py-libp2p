FROM python:3.13-slim

WORKDIR /app

# Prefer the system CA bundle: the base image's pip can still vendor the
# compromised eMudhra/emSign root (October 2026 CA certificate incident).
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

# Install uv via the official installer instead of pip, because the base image's
# pip may still trust the compromised eMudhra/emSign CA certificates. The floor
# matches [tool.uv] required-version in pyproject.toml; it is not a pin, so
# rebuilds pick up newer patched releases (GHSA-hq85-5cpj-mr62).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && uv --version \
    && uv_version="$(uv --version | awk '{print $2}')" \
    && { printf '%s\n%s\n' "0.13.4" "$uv_version" | sort -V -C \
         || { echo "uv ${uv_version} is below the required 0.13.4 floor (eMudhra/emSign CA incident)" >&2; exit 1; }; }

# Build context = repo root (same as interop/transport/Dockerfile for GitHub + local)
COPY . /app/py-libp2p

RUN uv venv /app/venv

# Interop/perf project: depends on libp2p from copied clone
COPY interop/perf/pyproject.toml .
# pip < 26.2.2 keeps trusting the compromised eMudhra/emSign CA certificates
RUN uv pip install --python /app/venv/bin/python "pip>=26.2.2" && \
    uv pip install --python /app/venv/bin/python --no-cache-dir -e .

COPY interop/perf/perf_test.py .

ENV PYTHONUNBUFFERED=1
ENV CI=true
ENV PATH="/app/venv/bin:${PATH}"

ENTRYPOINT ["/app/venv/bin/python", "perf_test.py"]
