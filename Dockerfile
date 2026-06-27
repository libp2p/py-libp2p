FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies required for cryptography (e.g. fastecdsa used by libp2p)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install the application
RUN pip install .

# Expose the API and Swarm ports
EXPOSE 5001
EXPOSE 4001

# Set the entrypoint to the CLI
ENTRYPOINT ["py-ipfs-lite"]
CMD ["--help"]
