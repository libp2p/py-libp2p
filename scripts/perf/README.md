# Local Python perf runner

`run_local_perf.py` runs the same `interop/perf/perf_test.py` binary as the unified-testing Docker perf harness, but coordinates listener and dialer with a temp file (`PERF_LOCAL_ADDR_FILE`) instead of Redis.

## Setup

From the py-libp2p repo root (the script auto-uses `.venv/bin/python` when present):

```bash
python -m venv .venv
uv pip install --python .venv/bin/python -e .
uv pip install --python .venv/bin/python redis cryptography
chmod +x scripts/perf/run_local_perf.py
```

`redis` is only used when `PERF_LOCAL_ADDR_FILE` is unset; local runs still import it today.

## Usage

```bash
# Default: tcp + noise + yamux
./scripts/perf/run_local_perf.py

# All 8 python self-test stacks
./scripts/perf/run_local_perf.py --matrix

# One matrix row
./scripts/perf/run_local_perf.py --stack-index 0

# Faster iteration
./scripts/perf/run_local_perf.py --quick -t tcp -s noise -m yamux

# Yamux tuning (forwarded from the shell)
PY_YAMUX_DISABLE_HYSTERESIS=1 ./scripts/perf/run_local_perf.py
PY_YAMUX_ASSUME_RTT_MS=1 PY_YAMUX_BATCH_THRESHOLD_DIV=2 ./scripts/perf/run_local_perf.py
PERF_WRITE_BLOCK_SIZE=65536 ./scripts/perf/run_local_perf.py --debug

# Full libp2p trace (slow on yamux; use for deep debugging only)
LIBP2P_DEBUG=DEBUG ./scripts/perf/run_local_perf.py --quick -t tcp -s noise -m yamux
LIBP2P_DEBUG=libp2p.stream_muxer.yamux:DEBUG ./scripts/perf/run_local_perf.py --quick
```

Dialer YAML results are printed to stdout; a summary table is printed to stderr at the end (median upload/download/latency per stack).

## Logging

`perf_test.py` supports three levels (mutually prioritized):

| Mode                 | How to enable                                                     | What you get                                                                                                                         |
| -------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Default**          | (nothing)                                                         | Minimal stderr; suitable for throughput runs                                                                                         |
| **Targeted interop** | `DEBUG=true`, `./run.sh --debug`, or `run_local_perf.py --debug`  | DEBUG on perf/TLS/mplex/yamux loggers; core `libp2p` stays capped. Also sets `PY_YAMUX_DEBUG=1` locally / on python Docker sides     |
| **Full libp2p**      | `LIBP2P_DEBUG=…` in the environment **before** the process starts | Standard py-libp2p logging (`libp2p.utils.logging` at import). Perf does not cap levels. **Very verbose and slow** on yamux 1GB runs |

`LIBP2P_DEBUG` uses the same syntax as elsewhere in py-libp2p (see `docs/getting_started.rst`), for example:

- `LIBP2P_DEBUG=DEBUG` — all libp2p modules
- `LIBP2P_DEBUG=stream_muxer.yamux:DEBUG,transport:INFO` — module-specific levels
- `LIBP2P_DEBUG_FILE=/path/to/log` — optional file sink (with `LIBP2P_DEBUG` set)

When both are set, **`LIBP2P_DEBUG` wins** (full logging); `DEBUG=true` alone does not imply `LIBP2P_DEBUG`.

For Docker perf: export on the host before `./run.sh`, e.g. `LIBP2P_DEBUG=DEBUG ./run.sh --impl-select python --yes` (not recommended for throughput benchmarking).

## Environment variables

| Variable                                                         | Role                                                        |
| ---------------------------------------------------------------- | ----------------------------------------------------------- |
| `TRANSPORT`, `SECURE_CHANNEL`, `MUXER`                           | Stack (CLI overrides defaults)                              |
| `IS_DIALER`                                                      | Set by the script (`true` / `false`)                        |
| `PERF_LOCAL_ADDR_FILE`                                           | Set by the script (coordination file)                       |
| `UPLOAD_BYTES`, `DOWNLOAD_BYTES`                                 | Payload sizes (dialer)                                      |
| `UPLOAD_ITERATIONS`, `DOWNLOAD_ITERATIONS`, `LATENCY_ITERATIONS` | Iteration counts                                            |
| `TEST_TIMEOUT_SECS`                                              | In-process wait for listener addr / peer (inside perf_test) |
| `PERF_TEST_TIMEOUT_SECS`                                         | Harness/subprocess timeout (same as `run.sh --timeout`)     |
| `PERF_WRITE_BLOCK_SIZE`                                          | Perf service write block size                               |
| `PY_YAMUX_*`                                                     | Python yamux hysteresis / autotune knobs (see below)        |
| `DEBUG`                                                          | Targeted interop perf logging (see [Logging](#logging))     |
| `LIBP2P_DEBUG`, `LIBP2P_DEBUG_FILE`                              | Full py-libp2p logging (see [Logging](#logging))            |

### `PY_YAMUX_*` tuning (python only)

| Variable                       | Default in code                  | Purpose                                                     |
| ------------------------------ | -------------------------------- | ----------------------------------------------------------- |
| `PY_YAMUX_RELEASE_ON_READ`     | on (`1`)                         | Release window credit on read when hysteresis defers GrowTo |
| `PY_YAMUX_ASSUME_RTT_MS`       | `1` when unset and ping RTT is 0 | Bootstrap autotune before measured RTT                      |
| `PY_YAMUX_BATCH_THRESHOLD_DIV` | `2`                              | GrowTo threshold = target // divisor                        |
| `PY_YAMUX_DISABLE_HYSTERESIS`  | off                              | Treat any positive delta as full GrowTo                     |
| `PY_YAMUX_DEBUG`               | off                              | Targeted yamux perf logs                                    |

#### Example scenarios

| Goal                                   | Command                                                                                      |
| -------------------------------------- | -------------------------------------------------------------------------------------------- |
| Baseline throughput (default autotune) | `./scripts/perf/run_local_perf.py --quick -t tcp -s noise -m yamux`                          |
| Compare without hysteresis             | `PY_YAMUX_DISABLE_HYSTERESIS=1 ./scripts/perf/run_local_perf.py --quick`                     |
| WAN-like bootstrap before ping RTT     | `PY_YAMUX_ASSUME_RTT_MS=50 ./scripts/perf/run_local_perf.py --quick`                         |
| Larger / earlier GrowTo batches        | `PY_YAMUX_BATCH_THRESHOLD_DIV=1 ./scripts/perf/run_local_perf.py --quick`                    |
| Defer read-side WINDOW_UPDATE          | `PY_YAMUX_RELEASE_ON_READ=0 ./scripts/perf/run_local_perf.py --quick`                        |
| Window/autotune traces (low overhead)  | `PY_YAMUX_DEBUG=1 ./scripts/perf/run_local_perf.py --quick` or `--debug`                     |
| Full yamux module trace (slow)         | `LIBP2P_DEBUG=stream_muxer.yamux:DEBUG ./scripts/perf/run_local_perf.py --quick`             |
| Docker harness, same tuning            | `PY_YAMUX_ASSUME_RTT_MS=1 ./perf/run.sh --impl-select python --yes -t tcp -s noise -m yamux` |

Combine knobs as needed, e.g. `PY_YAMUX_ASSUME_RTT_MS=10 PY_YAMUX_BATCH_THRESHOLD_DIV=1 ./scripts/perf/run_local_perf.py --matrix`.

Subprocess timeout: `--timeout SECS`, or `PERF_TEST_TIMEOUT_SECS` / `TEST_TIMEOUT_SECS` from the environment.

## Matrix stacks (`--list-stacks`)

Same as `python-v0.x` in unified-testing `perf/images.yaml`: tcp/ws × noise/tls × yamux/mplex (8 combinations).
