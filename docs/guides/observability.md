# Observability

This guide covers the Prometheus metrics exposed by `py-ipfs-lite`, what each metric
means, how to scrape and visualize them, and the important caveats you should know
before building a dashboard on them.

**Relevant examples:**

- [`examples/16_metrics_dashboard.py`](../../examples/16_metrics_dashboard.py) — start
  a peer, generate activity, scrape and print the metrics
- [`examples/17_concurrent_ingestion_benchmark.py`](../../examples/17_concurrent_ingestion_benchmark.py) —
  10 agents concurrently writing + background GC, demonstrates safe concurrent operation
- [`examples/21_resource_footprint.py`](../../examples/21_resource_footprint.py) —
  memory and CPU at rest and under load, real numbers to cite

**Run them:**

```bash
uv run python examples/16_metrics_dashboard.py
uv run python examples/17_concurrent_ingestion_benchmark.py
uv run python examples/21_resource_footprint.py
```

______________________________________________________________________

## Metrics Endpoint

When running the HTTP API daemon, all Prometheus metrics are exposed at:

```
GET http://127.0.0.1:5001/debug/metrics/prometheus
```

Response format: `text/plain; version=0.0.4` (standard Prometheus text exposition).

```bash
curl http://127.0.0.1:5001/debug/metrics/prometheus
```

______________________________________________________________________

## Exposed Metrics

All metrics are prefixed with `ipfs_`.

### Blockstore

| Metric                         | Type  | Description                                     |
| ------------------------------ | ----- | ----------------------------------------------- |
| `ipfs_blockstore_blocks_total` | Gauge | Current number of blocks in the blockstore      |
| `ipfs_blockstore_size_bytes`   | Gauge | Total byte size of all blocks in the blockstore |

These are updated on every `put_block()` (incremented) and `delete_block()` (decremented)
call by the `MetricsBlockStore` wrapper.

### Bitswap

| Metric                              | Type    | Description                                              |
| ----------------------------------- | ------- | -------------------------------------------------------- |
| `ipfs_bitswap_bytes_sent_total`     | Counter | Cumulative bytes sent to remote peers over Bitswap       |
| `ipfs_bitswap_bytes_received_total` | Counter | Cumulative bytes received from remote peers over Bitswap |

Both are monotonically increasing counters — use `rate()` in PromQL to get throughput.

### DHT

| Metric                           | Type      | Description                                          |
| -------------------------------- | --------- | ---------------------------------------------------- |
| `ipfs_dht_query_latency_seconds` | Histogram | Latency distribution of DHT `find_providers` queries |

Histogram buckets follow the default Prometheus SDK distribution. Use
`histogram_quantile(0.99, ...)` in PromQL to compute P99 lookup latency.

### Garbage Collection

| Metric                           | Type    | Description                                 |
| -------------------------------- | ------- | ------------------------------------------- |
| `ipfs_gc_runs_total`             | Counter | Total number of GC runs since process start |
| `ipfs_gc_reclaimed_blocks_total` | Counter | Total blocks deleted across all GC runs     |

______________________________________________________________________

## Example 16: Scraping Metrics

[`examples/16_metrics_dashboard.py`](../../examples/16_metrics_dashboard.py)

This example starts a peer, generates activity (50 node writes + a GC run), then fetches
and prints all `ipfs_` metrics:

```python
import trio
import httpx
from prometheus_client import start_http_server
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    # Start the Prometheus exporter on a standalone port (for in-process use)
    start_http_server(8000)

    peer = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    # Generate activity
    for i in range(50):
        await peer.add_node({"hello": f"world_{i}"}, codec="dag-cbor")

    await peer.gc()

    # Fetch and print metrics
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8000/metrics")
        for line in resp.text.split("\n"):
            if line.startswith("ipfs_") and not line.endswith("_created"):
                print(f"  {line}")

    await peer.close()

trio.run(main)
```

### Typical output

```
  ipfs_blockstore_blocks_total 0.0
  ipfs_blockstore_size_bytes 0.0
  ipfs_bitswap_bytes_sent_total_total 0.0
  ipfs_bitswap_bytes_received_total_total 0.0
  ipfs_gc_runs_total_total 1.0
  ipfs_gc_reclaimed_blocks_total_total 50.0
```

After GC, the blockstore gauges drop to `0.0` because all 50 nodes were unpinned and
reclaimed. The GC counter increments to `1` and reclaimed blocks to `50`.

______________________________________________________________________

## Example 17: Concurrent Ingestion — Safety Under Load

[`examples/17_concurrent_ingestion_benchmark.py`](../../examples/17_concurrent_ingestion_benchmark.py)

This example is framed as a **safety demonstration**, not a performance benchmark.
It proves that `py-ipfs-lite` does not corrupt the blockstore or deadlock when 10 agents
write concurrently while GC runs aggressively in the background every 500 ms.

```python
NUM_AGENTS = 10
NODES_PER_AGENT = 100

# 10 agents each write 100 nodes concurrently
# Background GC fires every 0.5s during ingestion
# Result: no data races, no deadlocks, GC correctly reclaims unpinned blocks
```

### What the benchmark output looks like

```
Unleashing 10 concurrent agents...
Agent 0 starting ingestion...
Agent 3 starting ingestion...
...
--- Triggering aggressive background GC (run 0) ---
--- GC complete. Reclaimed 47 blocks. ---
Agent 7 finished 100 nodes in 1.03s (97.1 nodes/sec)
...
==================================================
BENCHMARK COMPLETE
Total Nodes Ingested: 1000
Unique CIDs captured: 1000
Total Time: 1.18s
Aggregate Throughput: 847.46 nodes/sec
==================================================
```

> **Throughput ceiling caveat:** The aggregate throughput figure (~850 nodes/sec for
> small DAG-JSON nodes) reflects the current upstream constraint — `MerkleDag.add_file()`
> in `py-libp2p` performs synchronous blocking I/O under a global lock. This is a
> known `py-libp2p` issue, not a `py-ipfs-lite` bottleneck. The primary takeaway from
> this example is **correctness under concurrency**, not raw throughput.

The `RWLock` that makes this safe:

- Agents hold the lock in **read mode** while writing nodes — they run concurrently.
- GC acquires the lock in **exclusive write mode** — it waits for all agents to yield,
  then runs atomically.
- No manual coordination needed in user code.

______________________________________________________________________

## Example 21: Resource Footprint

[`examples/21_resource_footprint.py`](../../examples/21_resource_footprint.py)

This example measures the process memory and CPU at four stages using `psutil`:

```python
# Stage 1: Baseline Python interpreter
print_usage("Baseline (Python)")

# Stage 2: Peer started and idle
await peer.start()
await trio.sleep(1)
print_usage("Peer Idle")

# Stage 3: After ingesting 5000 nodes
for i in range(5000):
    await peer.add_node({"node_index": i, "data": "X" * 128}, codec="dag-json")
print_usage("Peak Load")

# Stage 4: After GC
await peer.gc()
print_usage("Post-GC")
```

### Typical numbers (Apple M-series, in-memory blockstore)

| Stage                  | RSS Memory | CPU   |
| ---------------------- | ---------- | ----- |
| Baseline (Python)      | ~35 MB     | ~0%   |
| Peer Idle              | ~55 MB     | ~0.5% |
| Peak Load (5000 nodes) | ~110 MB    | ~15%  |
| Post-GC                | ~60 MB     | ~1%   |

These numbers back up the "lite" in the project name — a running peer at idle costs
roughly **20 MB above the baseline Python interpreter**. Peak memory during heavy
ingestion scales with blockstore size (the in-memory store holds all blocks in RAM).
After GC reclaims unpinned blocks, memory returns close to idle levels.

For embedded or edge deployments (Raspberry Pi, Docker containers), use
`blockstore_type="filesystem"` so in-memory usage is bounded to block metadata
rather than full block content.

______________________________________________________________________

## Known Caveats

> **Read these before building a production dashboard.**

### 1. Metrics are process-global

`prometheus_client` registers all metrics in a module-level global registry. If you
instantiate multiple `Peer` objects in the same Python process, **all of them share the
same counters and gauges**. There is no per-instance labelling.

Consequence: `ipfs_blockstore_blocks_total` in a multi-peer process reflects the
combined block count across all peers, with no way to distinguish which peer each block
belongs to.

For multi-peer processes, consider either:

- Running each peer in a separate process with its own exporter port, or
- Treating the metrics as process-level aggregates (often acceptable for agent workloads).

### 2. Blockstore gauges do not reflect pre-existing on-disk data after a restart

The `ipfs_blockstore_blocks_total` and `ipfs_blockstore_size_bytes` gauges are
**incremental** — they start at `0` on process start and are updated on each
`put_block()` / `delete_block()` call. They do not scan the existing filesystem
blockstore on startup.

Consequence: if a daemon restarts with 10,000 blocks already on disk, the gauge will
show `0` until new blocks are added. It reflects only the activity in the **current
process lifetime**.

For accurate at-rest storage reporting, use `GET /api/v0/repo/stat` instead — that
endpoint scans all keys in the blockstore synchronously on each call.

______________________________________________________________________

## Prometheus Scrape Configuration

```yaml
scrape_configs:
  - job_name: py-ipfs-lite
    static_configs:
      - targets: ["127.0.0.1:5001"]
    metrics_path: /debug/metrics/prometheus
    scrape_interval: 15s
```

### Useful PromQL queries

```promql
# Bitswap receive throughput (bytes/sec, 1m average)
rate(ipfs_bitswap_bytes_received_total[1m])

# GC frequency (runs per hour)
rate(ipfs_gc_runs_total[1h]) * 3600

# Blocks reclaimed per GC run (rolling average)
rate(ipfs_gc_reclaimed_blocks_total[5m]) / rate(ipfs_gc_runs_total[5m])

# DHT P99 lookup latency
histogram_quantile(0.99, rate(ipfs_dht_query_latency_seconds_bucket[5m]))
```
