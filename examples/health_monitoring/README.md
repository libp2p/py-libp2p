# Health Monitoring Demo

Optional **Python-local** connection health demos for py-libp2p. The proactive
health monitor is **off by default** in `ConnectionConfig`.

User guide: `docs/connection_health_monitoring.rst` (after `make docs`).

## Live multi-peer demo (recommended)

Starts a hub plus N-1 local TCP leaves (default **25** peers), then runs
configurable scenarios (`all` by default):

- `healthy` — connect, echo, wait for monitor pings, print scores
- `disabled` — observer host with monitoring off (empty health API)
- `protect` — ConnMgr `Protect` so auto-replace skips those peers
- `traffic` — concurrent echo streams across leaves
- `churn` — drop some leaves and reprint health

```bash
. .venv/bin/activate
python -m examples.health_monitoring.live_demo
python -m examples.health_monitoring.live_demo --peers 25 --scenario all
python -m examples.health_monitoring.live_demo --peers 10 --scenario healthy,protect
python -m examples.health_monitoring.live_demo --gui tui
python -m examples.health_monitoring.live_demo --gui web --gui-port 8765
python -m examples.health_monitoring.live_demo --list-scenarios
# or, after install: health-monitoring-demo
```

Optional richer TUI: `pip install -e ".[health-demo]"` (installs `rich`).

Config-only API walkthrough (no real connections):

```bash
python examples/health_monitoring/basic_example.py
```

## Prometheus / Grafana (resource manager)

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

**Testing**

```bash
pytest tests/examples/test_health_monitoring_run_demo.py -v
pytest tests/examples/test_health_monitoring_live_demo.py -v
```

Stop:

```bash
pkill -f run_demo.py || true
cd examples/health_monitoring
docker compose down
```
