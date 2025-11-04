# Monitoring Demo

Configure Prometheus target (match exporter port):
```bash
cd examples/monitoring-demo
python configure.py --port 8000   # or: DEMO_EXPORTER_PORT=8010 python configure.py
docker compose up -d
```

Run exporter (auto-picks a free port; you can also set DEMO_EXPORTER_PORT):
```bash
cd ../../
. .venv/bin/activate
python examples/monitoring-demo/run_demo.py  # or: DEMO_EXPORTER_PORT=8010 python examples/monitoring-demo/run_demo.py
```

Open UIs:
- Prometheus: http://localhost:9090/targets
- Grafana: http://localhost:3000

Notes:
- The Grafana dashboard `py-libp2p Resource Manager` is auto-provisioned.
- If you change the exporter port, re-run `configure.py` and `docker compose restart prometheus`.

Stop:
```bash
pkill -f run_demo.py || true
cd examples/monitoring-demo
docker compose down
```
