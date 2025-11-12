FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    redis-tools \
    build-essential \
    cmake \
    pkg-config \
    libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the py-libp2p-${commitSha} folder so we can use it as a local dependency
COPY py-libp2p-* /app/py-libp2p

# Copy pyproject.toml and install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy the ping test implementation
COPY ping_test.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CI=true

# Set the entrypoint to run the ping test
ENTRYPOINT ["python", "ping_test.py"]
