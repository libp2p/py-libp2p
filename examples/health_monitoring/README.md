# Health Monitoring Demo

**Prerequisites:** The demo exposes metrics over HTTP for Prometheus. Install the client in your venv:

```bash
pip install prometheus-client
```

Configure Prometheus target (match exporter port):

```bash
cd examples/health_monitoring
python configure.py --port 8000   # or: DEMO_EXPORTER_PORT=8010 python configure.py
docker compose up -d
```

Run exporter (auto-picks a free port; you can also set DEMO_EXPORTER_PORT):

```bash
cd ../../
. .venv/bin/activate
python examples/health_monitoring/run_demo.py  # or: DEMO_EXPORTER_PORT=8010 python examples/health_monitoring/run_demo.py
```

Open UIs:

- Prometheus: http://localhost:9090/targets
- Grafana: http://localhost:3000

**Validating the data**

The demo uses fixed limits: **10 connections**, **20 streams**, **32 MB** memory. Each second it tries to add 1 connection, 1 stream (if there is at least one connection), and 100–500 KB memory per peer. So over time you should see usage rise until it hits the limits, then blocks.

1. **Exporter vs logs** (with `run_demo.py` running):

   ```bash
   curl -s http://localhost:8000/metrics | grep -E '^libp2p_rcmgr_(connections|streams|memory|blocked)'
   ```

   Compare the numbers with what the demo prints: `Current: N conns, M streams, K bytes memory` and `Blocked: ...`. The gauges should match.

1. **Prometheus** (http://localhost:9090 → Graph):

   - `libp2p_rcmgr_connections{scope="system"}` — total connections (should stay ≤ 10).
   - `libp2p_rcmgr_streams{scope="system"}` — total streams (≤ 20).
   - `libp2p_rcmgr_memory{scope="system"}` — bytes (≤ 32*1024*1024).
   - `libp2p_rcmgr_blocked_resources` — blocked events; should increase when you are at a limit.

1. **Sanity checks**: Connections and streams should level off at 10 and 20; memory at or below 32 MB. After ~15–20 seconds you should see some blocked resources (connections or memory). The Grafana dashboard panels use these same metrics.

Notes:

- The Grafana dashboard `py-libp2p Resource Manager` is auto-provisioned.
- If you change the exporter port, re-run `configure.py` and `docker compose restart prometheus`.
- Prometheus reaches the host via `host.docker.internal` (docker-compose sets `host-gateway`). If the py-libp2p target stays DOWN, try the Docker bridge IP in `prometheus.yml` (e.g. `172.17.0.1:8000` from `ip addr show docker0`) or your machine’s IP.
- If port 8000 is already in use, run the demo on another port (e.g. `python run_demo.py --port 8001`), then run `configure.py --port 8001` and `docker compose restart prometheus`.

**Testing**

Tests for `run_demo.py` (different parameters, limit enforcement) live under the main test suite:

```bash
pytest tests/examples/test_health_monitoring_run_demo.py -v
```

Stop:

```bash
pkill -f run_demo.py || true
cd examples/health_monitoring
docker compose down
```
