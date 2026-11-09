FROM python:3.13-slim

WORKDIR /app

# Prefer the system CA bundle: the base image's pip can still vendor the
# compromised eMudhra/emSign root (October 2026 CA certificate incident).
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

# Copy the py-libp2p-${commitSha} folder so we can use it as a local dependency
COPY ./ /app/py-libp2p

# Create virtual environment using uv (as per contributing.rst)
RUN uv venv /app/venv

# Copy pyproject.toml and install Python dependencies using uv
# Use the venv's Python explicitly with uv pip
COPY interop/transport/pyproject.toml .
# pip < 26.2.2 keeps trusting the compromised eMudhra/emSign CA certificates
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
