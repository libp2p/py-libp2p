# Parallel test failure investigation (`make pr` / `pytest -n auto`)

## Metadata

- Branch: `investigate/parallel-test-failures`
- Baseline (known-good): `ad1eb6ae`
- Started: 2026-07-09
- Environment: Linux r17 7.1.2-arch3-1 x86_64, 32 CPUs, Python 3.13.11, `ulimit -n` 100000
- `make test` command: `python -m pytest tests -n auto`

## Failing tests (6)

| Test                                                                                                          | Symptom                                         | First seen         |
| ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | ------------------ |
| `tests/core/identity/identify/test_identify_integration.py::test_identify_multi_transport_host_addresses`     | Address not advertised in `listen_addrs`        | User `make pr` run |
| `tests/core/identity/identify/test_identify_integration.py::test_identify_protocol_varint_format_integration` | `listen_addrs == []`                            | User `make pr` run |
| `tests/core/identity/identify/test_identify_integration.py::test_identify_protocol_raw_format_integration`    | `listen_addrs == []`                            | User `make pr` run |
| `tests/core/identity/identify/test_identify.py::test_identify_protocol`                                       | `ValueError: Could not deserialize key data`    | User `make pr` run |
| `tests/core/test_libp2p/test_libp2p.py::test_host_connect`                                                    | Advertised addr not in peerstore                | User `make pr` run |
| `tests/core/transport/quic/test_integration.py::test_yamux_stress_ping`                                       | Automatic identify did not cache ping within 5s | User `make pr` run |

## Hypothesis

Load-sensitive timing races in identify / address propagation under xdist full-suite parallel execution. Recent commits (#1372 interop, #1374 QUIC mypy) are unlikely culprits.

## Reproducibility results

### Full suite (`make test`, `-n auto`)

| Run       | Commit | Pass/Fail | Failed tests |
| --------- | ------ | --------- | ------------ |
| (pending) |        |           |              |

### Parallelism ladder

| `-n`      | Runs | Failures | Notes |
| --------- | ---- | -------- | ----- |
| (pending) |      |          |       |

## Bisect (if run)

- Good: `ad1eb6ae`
- Bad: (pending)
- Result: (pending)

## Experiments

### A — empty listen_addrs

(pending)

### B — framed read vs `stream.read(8192)`

(pending)

### C — identify wait after `connect()`

(pending)

### D — resource limits (`ulimit`, `ss -s`)

(pending)

## Root cause (confirmed)

(pending)

## Fix applied

(pending)

## Validation

| Run       | `make pr` | Notes |
| --------- | --------- | ----- |
| (pending) |           |       |
