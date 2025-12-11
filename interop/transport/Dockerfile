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

# Install py-multihash from git first (required by libp2p)
# The fork version has Func and FuncReg attributes needed by py-libp2p
# We install with dependencies to get base58 and other required packages
RUN pip install --no-cache-dir --force-reinstall "py-multihash @ git+https://github.com/sumanjeet0012/py-multihash.git@cb23eaa3c66d977ae7f4ce777cad5c2566a7c3de" && \
    python -c "import multihash; assert hasattr(multihash, 'Func'), 'py-multihash missing Func attribute'; print('✓ py-multihash has Func attribute')"

# Copy interop test pyproject.toml and install (this will install libp2p and its dependencies)
COPY interop/transport/pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy the ping test implementation
COPY interop/transport/ping_test.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CI=true

# Set the entrypoint to run the ping test
ENTRYPOINT ["python", "ping_test.py"]
