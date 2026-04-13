# Interop Directory

This directory contains **interoperability and performance test material** for py-libp2p. It is used by more than one harness: the [unified-testing framework](https://github.com/libp2p/unified-testing) and [libp2p/test-plans](https://github.com/libp2p/test-plans) (transport-interop and related suites) are maintained **independently**; both can build Docker images and run cross-implementation tests from this repo.

## Purpose

The `interop/` directory houses the Docker images, test scripts, and configuration needed to run py-libp2p in cross-implementation tests. Keeping this material **in the py-libp2p repository** means:

- Enables **local testing** against other libp2p implementations (Rust, Go, JS, .NET) without syncing between repos
- Serves as an **example** for setting up Docker-based protocol tests with py-libp2p
- Keeps test implementations versioned and developed alongside the library

## Directory Layout

```
interop/
├── perf/          # Performance (throughput, latency) tests
│   ├── Dockerfile      # Builds image for perf protocol testing
│   ├── perf_test.py   # Test application (listener + dialer)
│   └── pyproject.toml # Dependencies (libp2p, redis, etc.)
└── transport/     # Transport interoperability tests
    ├── Dockerfile
    ├── ping_test.py
    └── pyproject.toml
```

Each subdirectory corresponds to a **test type** (perf vs transport) consumed by the harnesses below.

## Relationship to libp2p/test-plans

The **canonical** transport ping harness is **`interop/transport/ping_test.py`** in this repository.

The **test-plans** repo builds a **python-v0.x** image for [transport-interop](https://github.com/libp2p/test-plans/tree/master/transport-interop) using its own **`impl/python/v0.x/Dockerfile`**: it vendors a py-libp2p tree (zip/commit), may apply **test-plans-only** patches (for example a Yamux interoperability fix), sets **`ENTRYPOINT`** to run `ping_test.py` with **`--test-plans`**, and pins dependencies via **`impl/python/v0.x/pyproject.toml`**. That layout tracks this repo; **do not treat the test-plans copy of `ping_test.py` as the source of truth**—change it here, then sync or bump the pinned commit in test-plans.

By contrast, **`interop/transport/Dockerfile`** in py-libp2p targets the **unified-testing** workflow (venv via **uv**, Python 3.13 slim, default **`ENTRYPOINT`** without `--test-plans`). The two Dockerfiles are **not** interchangeable; only the **script and library expectations** should stay aligned.

## How It Integrates with Unified-Testing

The unified-testing framework (see `unified-testing/docs/`) runs tests by:

1. **Building Docker images** – Uses `images.yaml` to define implementations. For py-libp2p, the build uses `source.type: github` (or `local`) pointing at this repo, with a `dockerfile` path such as `interop/perf/Dockerfile`.
1. **Running tests** – The framework starts **listener** and **dialer** containers on a shared network, coordinates them via **Redis**, and collects results.

### Perf Tests (`interop/perf/`)

Perf tests measure:

- **Upload throughput** – How fast the dialer sends data to the listener
- **Download throughput** – How fast the dialer receives data from the listener
- **Latency** – Round-trip time for small messages

The test app (`perf_test.py`) implements the [libp2p perf protocol](https://github.com/libp2p/specs/blob/master/perf/perf.md) (`/perf/1.0.0`) and follows [write-a-perf-test-app.md](https://github.com/libp2p/unified-testing/blob/master/docs/write-a-perf-test-app.md):

- Reads config from environment variables (`IS_DIALER`, `REDIS_ADDR`, `TEST_KEY`, `TRANSPORT`, etc.)
- Listener publishes its multiaddr to Redis; dialer polls and connects
- Dialer runs upload/download/latency iterations and outputs YAML results to stdout
- All logging goes to stderr (stdout is reserved for results)

### Transport Tests (`interop/transport/`)

Transport tests verify that py-libp2p can establish connections and exchange protocols with other implementations over various transport, secure channel, and muxer combinations (TCP, QUIC, WebSocket, Noise, TLS, yamux, mplex).

The entry point is **`ping_test.py`**, which supports **unified-testing** (YAML / `TEST_KEY` Redis keys) and, when invoked with **`--test-plans`**, the **test-plans** harness (JSON on stdout, `listenerAddr` Redis key). See **`interop/transport/pyproject.toml`** for install-time dependencies.

## Build Context

When building from the py-libp2p repo:

- **Build context** = repository root (not `interop/perf/` or `interop/transport/`)
- The Dockerfile uses `COPY . /app/py-libp2p` to include the full libp2p source, then copies the test script and installs dependencies so the test app uses the in-repo libp2p.

This ensures each Docker image is built against the exact py-libp2p version in the repo or specified commit.

## Running Locally

To run interop tests, use the unified-testing framework:

```bash
# From the unified-testing repo
cd perf
./run.sh --impl-select "python-v0.x"   # When python is in images.yaml
```

To run the perf test script directly (e.g. for development), see `examples/perf/perf_example.py` and the [perf protocol documentation](../../libp2p/perf/).

## Relationship to CI

- Code in `interop/` is **not** run by py-libp2p's own CI (which uses `tests/`).
- **unified-testing** runs this code when py-libp2p is listed in `images.yaml` and the perf/transport suite is executed.
- **test-plans** CI runs transport-interop (and may build the Python image from a pinned commit of this repo).

## References

- [libp2p/test-plans](https://github.com/libp2p/test-plans) – transport-interop and other matrix tests
- [Unified-testing framework](https://github.com/libp2p/unified-testing) – Bash + Docker test runner
- [write-a-perf-test-app.md](https://github.com/libp2p/unified-testing/blob/master/docs/write-a-perf-test-app.md) – Perf test app specification
- [write-a-transport-test-app.md](https://github.com/libp2p/unified-testing/blob/master/docs/write-a-transport-test-app.md) – Transport test app specification
- [libp2p perf protocol spec](https://github.com/libp2p/specs/blob/master/perf/perf.md)
