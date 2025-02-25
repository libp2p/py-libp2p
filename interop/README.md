# Python (py-libp2p) Interoperability Testing

This directory contains tools for testing interoperability between the Python implementation of libp2p (py-libp2p) and other libp2p implementations.

## Prerequisites

- Docker
- Docker Compose (for multi-implementation testing)
- A running Redis instance (for coordination between implementations)

## Building the Image

```bash
docker build -t py-libp2p-interop .
```

## Running Tests

### Setup Redis Network

First, create a Docker network for the tests:

```bash
docker network create libp2p-test
```

Start a Redis instance if you don't have one running:

```bash
docker run --name redis --network libp2p-test -d redis
```

### Running as a Listener

```bash
docker run --network libp2p-test -e ROLE=listener -e TRANSPORT=tcp -e SECURE_CHANNEL=noise -e MUXER=mplex -e REDIS_HOST=redis py-libp2p-interop
```

### Running as a Dialer

```bash
docker run --network libp2p-test -e ROLE=dialer -e TRANSPORT=tcp -e SECURE_CHANNEL=noise -e MUXER=mplex -e REDIS_HOST=redis py-libp2p-interop
```

## Configuration Options

The py-libp2p interoperability test supports the following environment variables:

- `ROLE`: Either `listener` or `dialer` (required)
- `TRANSPORT`: Transport protocol to use. Currently supports `tcp` (required)
- `SECURE_CHANNEL`: Security protocol to use. Supports `noise` or `secio` (required)
- `MUXER`: Stream multiplexer to use. Currently supports `mplex` (required)
- `LISTENER_PORT`: Port for the listener (default: 8000)
- `REDIS_HOST`: Redis hostname (default: "redis")
- `REDIS_PORT`: Redis port (default: 6379)

## Testing with Multiple Implementations

To test interoperability between py-libp2p and other implementations, you can use Docker Compose to orchestrate the tests:

```yaml
version: '3'

services:
  redis:
    image: redis
    networks:
      - libp2p-test

  py-libp2p-listener:
    image: py-libp2p-interop
    environment:
      - ROLE=listener
      - TRANSPORT=tcp
      - SECURE_CHANNEL=noise
      - MUXER=mplex
      - REDIS_HOST=redis
    networks:
      - libp2p-test
    depends_on:
      - redis

  go-libp2p-dialer:
    image: go-libp2p-interop  # Replace with the appropriate Go libp2p image
    environment:
      - ROLE=dialer
      - TRANSPORT=tcp
      - SECURE_CHANNEL=noise
      - MUXER=mplex
      - REDIS_HOST=redis
    networks:
      - libp2p-test
    depends_on:
      - redis
      - py-libp2p-listener

networks:
  libp2p-test:
```

Run with:

```bash
docker-compose up
```

## Troubleshooting

If you encounter Redis connection issues, ensure:
1. Redis container is running and accessible
2. All containers are on the same network
3. Redis hostname resolution is working from your containers