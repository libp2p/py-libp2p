# Use Python slim image
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
    git \
    gcc \
    g++ \
    make \
    libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Clone py-libp2p (this ensures we have the full project)
RUN git clone https://github.com/libp2p/py-libp2p.git .

# Install py-libp2p and its dependencies
RUN pip install -e .
RUN pip install redis

# Copy our test script
COPY test.py .

# Environment variables for configuration
ENV REDIS_HOST=redis
ENV ROLE=listener
ENV TRANSPORT=tcp
ENV SECURE_CHANNEL=noise
ENV MUXER=mplex

# Run the test script
CMD ["python", "test.py"]