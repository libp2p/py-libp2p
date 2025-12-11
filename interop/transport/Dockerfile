FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    redis-tools \
    build-essential \
    cmake \
    pkg-config \
    libgmp-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy the py-libp2p-${commitSha} folder so we can use it as a local dependency
COPY ./ /app/py-libp2p

# Copy pyproject.toml and install Python dependencies
COPY interop/transport/pyproject.toml .
# Install py-multihash from git first to ensure it's available (required by libp2p)
# This is needed because pip might not resolve git dependencies correctly when installing from local file
RUN pip install --no-cache-dir "py-multihash @ git+https://github.com/sumanjeet0012/py-multihash.git@cb23eaa3c66d977ae7f4ce777cad5c2566a7c3de" && \
    pip install --no-cache-dir -e .

# Copy the ping test implementation
COPY interop/transport/ping_test.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CI=true

# Set the entrypoint to run the ping test
ENTRYPOINT ["python", "ping_test.py"]
