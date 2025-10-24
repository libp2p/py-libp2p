# Simple Production Deployment

This directory contains a simplified production deployment example for the Python libp2p WebSocket transport, featuring echo/ping protocols, message passing, and file transfer capabilities. Based on patterns from JavaScript and Go libp2p implementations.

## 🚀 Quick Start

### Docker Compose (Recommended)

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f libp2p-websocket

# Stop services
docker-compose down
```

### Direct Docker Build

```bash
# Build the image
docker build -t libp2p-production .

# Run the container
docker run -d --name libp2p-websocket -p 8080:8080 -p 8081:8081 libp2p-production

# View logs
docker logs -f libp2p-websocket

# Stop and remove
docker stop libp2p-websocket && docker rm libp2p-websocket
```

### Direct Python Execution

```bash
# Start server
python main.py

# Test with curl
curl http://localhost:8081/health
curl http://localhost:8081/metrics
```

## 📁 Directory Structure

```
production_deployment/
├── main.py              # Main production application
├── cert_manager.py      # Certificate management
├── test_production.py   # Test script
├── Dockerfile           # Docker image
├── docker-compose.yml # Docker Compose
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

## 🏗️ Architecture

### Components

1. **libp2p-websocket**: Main application service with WebSocket transport
1. **cert-manager**: AutoTLS certificate management service

### Features

- ✅ **Echo Protocol** (`/echo/1.0.0`): Message echoing for connectivity testing
- ✅ **Ping Protocol** (`/ipfs/ping/1.0.0`): Standard libp2p ping for latency testing
- ✅ **Message Passing** (`/message/1.0.0`): Peer-to-peer messaging with acknowledgments
- ✅ **File Transfer** (`/file/1.0.0`): Chunked file sharing between peers
- ✅ **AutoTLS Support**: Automatic certificate generation and renewal
- ✅ **Health Checks**: HTTP endpoints for monitoring
- ✅ **Security**: Non-root containers, secure defaults
- ✅ **Scaling**: Multi-instance deployment support

## 📊 Protocols

### Echo Protocol (`/echo/1.0.0`)

Simple message echoing protocol for testing connectivity and basic communication.

**Usage:**

```bash
# Test echo protocol
curl -X POST http://localhost:8080/echo -d "Hello World!"
```

### Ping Protocol (`/ipfs/ping/1.0.0`)

Standard libp2p ping protocol for connectivity testing and latency measurement.

**Usage:**

```bash
# Test ping protocol
curl -X GET http://localhost:8080/ping
```

### Message Passing (`/message/1.0.0`)

Peer-to-peer messaging protocol with acknowledgment support.

**Usage:**

```bash
# Send message
curl -X POST http://localhost:8080/message -d "Production message!"
```

### File Transfer (`/file/1.0.0`)

File sharing protocol with chunked transfer and progress tracking.

**Usage:**

```bash
# Upload file
curl -X POST http://localhost:8080/file -F "file=@example.txt"
```

## 🔧 Configuration

### Environment Variables

| Variable       | Default         | Description              |
| -------------- | --------------- | ------------------------ |
| `LOG_LEVEL`    | `INFO`          | Logging level            |
| `PORT`         | `8080`          | WebSocket port           |
| `HEALTH_PORT`  | `8081`          | Health check port        |
| `DOMAIN`       | `libp2p.local`  | AutoTLS domain           |
| `STORAGE_PATH` | `autotls-certs` | Certificate storage path |

### Ports

| Port   | Service   | Description              |
| ------ | --------- | ------------------------ |
| `8080` | WebSocket | Main WebSocket service   |
| `8081` | Health    | Health check and metrics |

## 🐳 Docker Commands

### Build and Run

```bash
# Build the image
docker build -t libp2p-production .

# Run the container
docker run -d --name libp2p-websocket -p 8080:8080 -p 8081:8081 libp2p-production

# View logs
docker logs -f libp2p-websocket

# Stop and remove
docker stop libp2p-websocket && docker rm libp2p-websocket
```

### Docker Compose

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Scale services
docker-compose up -d --scale libp2p-websocket=3

# Stop services
docker-compose down

# Clean up volumes
docker-compose down -v
```

## 🧪 Testing

### Manual Testing

1. **Start Server:**

   ```bash
   docker-compose up -d
   ```

1. **Test Health Check:**

   ```bash
   curl http://localhost:8081/health
   ```

1. **Test Metrics:**

   ```bash
   curl http://localhost:8081/metrics
   ```

1. **Test Protocols:**

   ```bash
   # Echo protocol
   curl -X POST http://localhost:8080/echo -d "Test message"

   # Ping protocol
   curl -X GET http://localhost:8080/ping

   # Message passing
   curl -X POST http://localhost:8080/message -d "Production message!"

   # File transfer
   curl -X POST http://localhost:8080/file -F "file=@example.txt"
   ```

### Automated Testing

```bash
# Run test script
python test_production.py

# Run with Docker Compose
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f libp2p-websocket
```

## 📈 Monitoring

### Health Checks

The application includes built-in health checks:

- **Docker Health Check**: Automatic container health monitoring
- **Service Health**: WebSocket service availability
- **Certificate Health**: AutoTLS certificate status

### Logging

Structured logging with different levels:

- **INFO**: General application events
- **WARNING**: Non-critical issues
- **ERROR**: Critical errors
- **DEBUG**: Detailed debugging information

### Statistics

The application tracks:

- Messages sent/received
- Pings sent/received
- Files sent/received
- Connection statistics
- Protocol usage

## 🔒 Security

### AutoTLS

- Automatic certificate generation
- Certificate renewal before expiration
- Secure WebSocket (WSS) support
- Domain-based certificate management

### Production Security

- Non-root container execution
- Minimal attack surface
- Secure defaults
- Input validation
- Error handling

## 🚀 Deployment

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run server
python main.py

# Test health
curl http://localhost:8081/health
```

### Production Deployment

```bash
# Build production image
docker build -t libp2p-production:latest .

# Deploy with Docker Compose
docker-compose up -d

# Monitor deployment
docker-compose logs -f
```

## 📚 Examples

### Basic Usage

```python
from main import ProductionApp

# Create app
config = {
    'port': '8080',
    'health_port': '8081',
    'domain': 'libp2p.local',
    'storage_path': 'autotls-certs',
    'log_level': 'INFO'
}

app = ProductionApp(config)

# Start server
await app.start()
```

### Advanced Configuration

```python
# Custom configuration
config = {
    'port': '8080',
    'health_port': '8081',
    'domain': 'myapp.local',
    'storage_path': '/custom/cert/path',
    'log_level': 'DEBUG'
}

app = ProductionApp(config)
await app.start()
```

## 🎯 Success Criteria

- ✅ Echo protocol works end-to-end
- ✅ Ping protocol works end-to-end
- ✅ Message passing works end-to-end
- ✅ File transfer works end-to-end
- ✅ AutoTLS certificates are generated and renewed
- ✅ WebSocket transport supports both WS and WSS
- ✅ Production deployment is containerized
- ✅ Health checks and monitoring are functional
- ✅ All protocols are tested and validated

## 🔗 Related Documentation

- [libp2p WebSocket Transport](../libp2p/transport/websocket/)
- [AutoTLS Implementation](../libp2p/transport/websocket/autotls.py)
- [Echo Protocol Examples](../examples/echo/)
- [Ping Protocol Examples](../examples/ping/)

## 📝 Notes

This simplified production deployment demonstrates:

1. **Protocol Implementation**: Echo, ping, message passing, and file transfer
1. **WebSocket Transport**: Full WS/WSS support with AutoTLS
1. **Production Readiness**: Containerization, health checks, monitoring
1. **Real-world Usage**: Practical examples for peer-to-peer communication
1. **Security**: AutoTLS certificate management and secure defaults

The implementation follows patterns from JavaScript and Go libp2p implementations while providing a Python-native experience with production-grade features.
