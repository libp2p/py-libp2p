# Production Deployment Examples

This directory contains comprehensive production deployment examples for the Python libp2p WebSocket transport, based on patterns from JavaScript and Go libp2p implementations.

## 🚀 Quick Start

### Docker Compose (Recommended for Development)

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f libp2p-websocket

# Scale the service
docker-compose up -d --scale libp2p-websocket=3
```

### Kubernetes (Production)

```bash
# Create namespace
kubectl create namespace libp2p-production

# Deploy the application
kubectl apply -f kubernetes/

# Check status
kubectl get pods -n libp2p-production
```

## 📁 Directory Structure

```
production_deployment/
├── Dockerfile                 # Multi-stage production Docker image
├── docker-compose.yml        # Complete stack with monitoring
├── main.py                   # Production application
├── requirements.txt          # Python dependencies
├── prometheus.yml            # Prometheus configuration
├── nginx/
│   └── nginx.conf            # Load balancer configuration
├── kubernetes/
│   ├── deployment.yaml      # Kubernetes deployment
│   └── ingress.yaml         # Ingress and networking
└── README.md                # This file
```

## 🏗️ Architecture

### Components

1. **libp2p-websocket**: Main application service
2. **redis**: Inter-node communication and caching
3. **prometheus**: Metrics collection
4. **grafana**: Monitoring dashboards
5. **nginx**: Load balancer and SSL termination
6. **cert-manager**: AutoTLS certificate management

### Features

- ✅ **AutoTLS Support**: Automatic certificate generation and renewal
- ✅ **Load Balancing**: Nginx-based load balancing
- ✅ **Monitoring**: Prometheus + Grafana integration
- ✅ **Health Checks**: Comprehensive health monitoring
- ✅ **Security**: Non-root containers, network policies
- ✅ **Scaling**: Horizontal pod autoscaling
- ✅ **Persistence**: Persistent storage for certificates and data

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `info` | Logging level |
| `HTTP_PORT` | `8080` | HTTP/WebSocket port |
| `HTTPS_PORT` | `8443` | HTTPS/WSS port |
| `AUTO_TLS_ENABLED` | `false` | Enable AutoTLS |
| `AUTO_TLS_DOMAIN` | `libp2p.local` | AutoTLS domain |
| `REDIS_URL` | `redis://redis:6379` | Redis connection URL |
| `METRICS_ENABLED` | `true` | Enable metrics collection |

### Docker Compose Configuration

```yaml
# Custom configuration
services:
  libp2p-websocket:
    environment:
      - AUTO_TLS_ENABLED=true
      - AUTO_TLS_DOMAIN=myapp.local
      - LOG_LEVEL=debug
```

### Kubernetes Configuration

```yaml
# Custom environment
env:
- name: AUTO_TLS_ENABLED
  value: "true"
- name: AUTO_TLS_DOMAIN
  value: "myapp.local"
```

## 📊 Monitoring

### Metrics Endpoints

- **Health**: `http://localhost:8080/health`
- **Metrics**: `http://localhost:9090/metrics`
- **Grafana**: `http://localhost:3000` (admin/admin)

### Key Metrics

- `libp2p_connections_total`: Total connections
- `libp2p_connections_active`: Active connections
- `libp2p_messages_sent_total`: Messages sent
- `libp2p_messages_received_total`: Messages received
- `libp2p_uptime_seconds`: Application uptime

### Grafana Dashboards

Pre-configured dashboards include:
- **libp2p Overview**: High-level metrics
- **Connection Metrics**: Connection statistics
- **Message Flow**: Message throughput
- **System Resources**: CPU, memory, network

## 🔒 Security

### Container Security

- Non-root user execution
- Read-only root filesystem
- Minimal base images
- Security context constraints

### Network Security

- Network policies for pod isolation
- TLS encryption for all communications
- Rate limiting and DDoS protection
- Security headers

### Certificate Management

- Automatic TLS certificate generation
- Certificate renewal before expiry
- Wildcard domain support
- Secure certificate storage

## 🚀 Deployment Strategies

### Rolling Updates

```bash
# Update application
kubectl set image deployment/libp2p-websocket libp2p-websocket=libp2p-websocket:v2.0.0

# Check rollout status
kubectl rollout status deployment/libp2p-websocket
```

### Blue-Green Deployment

```bash
# Deploy new version
kubectl apply -f kubernetes/deployment-green.yaml

# Switch traffic
kubectl patch service libp2p-websocket-service -p '{"spec":{"selector":{"version":"v2.0.0"}}}'
```

### Canary Deployment

```bash
# Deploy canary version
kubectl apply -f kubernetes/canary-deployment.yaml

# Gradually increase traffic
kubectl patch service libp2p-websocket-service -p '{"spec":{"selector":{"version":"canary"}}}'
```

## 🔧 Troubleshooting

### Common Issues

1. **Certificate Issues**
   ```bash
   # Check certificate status
   kubectl logs -n libp2p-production deployment/libp2p-websocket | grep -i cert
   ```

2. **Connection Issues**
   ```bash
   # Check network policies
   kubectl get networkpolicies -n libp2p-production
   ```

3. **Performance Issues**
   ```bash
   # Check resource usage
   kubectl top pods -n libp2p-production
   ```

### Debug Commands

```bash
# View application logs
kubectl logs -f deployment/libp2p-websocket -n libp2p-production

# Check service endpoints
kubectl get endpoints -n libp2p-production

# Test connectivity
kubectl exec -it deployment/libp2p-websocket -n libp2p-production -- curl localhost:8080/health
```

## 📈 Scaling

### Horizontal Pod Autoscaling

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: libp2p-websocket-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: libp2p-websocket
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### Vertical Pod Autoscaling

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: libp2p-websocket-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: libp2p-websocket
  updatePolicy:
    updateMode: "Auto"
```

## 🧪 Testing

### Load Testing

```bash
# Install k6
curl https://github.com/grafana/k6/releases/download/v0.47.0/k6-v0.47.0-linux-amd64.tar.gz -L | tar xvz --strip-components 1

# Run load test
k6 run load-test.js
```

### Integration Testing

```bash
# Run integration tests
pytest tests/integration/test_production_deployment.py -v
```

## 📚 References

- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Kubernetes Production Patterns](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [Prometheus Monitoring](https://prometheus.io/docs/guides/go-application/)
- [Nginx WebSocket Proxy](https://nginx.org/en/docs/http/websocket.html)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](../../LICENSE-APACHE) file for details.
