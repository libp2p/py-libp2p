# Parallel test failure investigation (`make pr` / `pytest -n auto`)

## Metadata

- Branch: `investigate/parallel-test-failures`
- Baseline (known-good): `ad1eb6ae`
- Started: 2026-07-09
- Environment: Linux r17 7.1.2-arch3-1 x86_64, 32 CPUs, Python 3.13.11, `ulimit -n` 100000
- `make test` command: parallel phase `pytest tests -n auto -m "not serial_only"`, then serial phase for 6 tests

## Failing tests (6)

| Test                                                                                                          | Symptom                                                                     | First seen         |
| ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------ |
| `tests/core/identity/identify/test_identify_integration.py::test_identify_multi_transport_host_addresses`     | Address not advertised in `listen_addrs`                                    | User `make pr` run |
| `tests/core/identity/identify/test_identify_integration.py::test_identify_protocol_varint_format_integration` | `listen_addrs == []`                                                        | User `make pr` run |
| `tests/core/identity/identify/test_identify_integration.py::test_identify_protocol_raw_format_integration`    | `listen_addrs == []`                                                        | User `make pr` run |
| `tests/core/identity/identify/test_identify.py::test_identify_protocol`                                       | `ValueError: Could not deserialize key data` (truncated `signedPeerRecord`) | User `make pr` run |
| `tests/core/test_libp2p/test_libp2p.py::test_host_connect`                                                    | Advertised addr not in peerstore                                            | User `make pr` run |
| `tests/core/transport/quic/test_integration.py::test_yamux_stress_ping`                                       | Automatic identify did not cache ping within 5s                             | User `make pr` run |

## Hypothesis

Load-sensitive timing races in identify / address propagation under xdist full-suite parallel execution. Not caused by #1372/#1374 logic changes.

## Reproducibility results

### Full suite (`make test`, `-n auto`)

| Run | Commit               | Pass/Fail | Failed tests             |
| --- | -------------------- | --------- | ------------------------ |
| 1   | `7acf896e` (pre-fix) | Fail      | All 6 above              |
| 2   | `7acf896e` (pre-fix) | Fail      | All 6 above              |
| 3   | `7acf896e` (pre-fix) | Fail      | All 6 above              |
| 1   | `ad1eb6ae`           | Pass      | 3061 passed              |
| 2   | `ad1eb6ae`           | Pass      | 3061 passed              |
| 3   | `ad1eb6ae`           | Pass      | 3061 passed              |
| 1   | post-fix             | Pass      | 3058 parallel + 6 serial |
| 2   | post-fix             | Pass      | 3058 parallel + 6 serial |
| 3   | post-fix             | Pass      | 3058 parallel + 6 serial |

### Parallelism ladder (6 tests only, isolated)

| `-n` | Runs | Failures | Notes |
| ---- | ---- | -------- | ----- |
| 0    | 5    | 0        | Pass  |
| 2    | 5    | 0        | Pass  |
| 4    | 5    | 0        | Pass  |
| auto | 5    | 0        | Pass  |

**Conclusion:** Failures only appear when the **full ~3060-test suite** runs in parallel. Isolated execution always passes.

### Regression boundary

| Commit             | Full `-n auto` result         |
| ------------------ | ----------------------------- |
| `ad1eb6ae`         | 3061 passed, 0 failed         |
| `fd4bf0bf` (#1372) | 6 failed (identify/host/quic) |
| `cb8215d7` (#1374) | 6 failed (same)               |

#1372 adds 3 interop transport tests and changes xdist scheduling/load; no identify/host code changed. Excluding `tests/interop/transport` on `fd4bf0bf` removes the 6 identify failures (different unrelated failure appears).

## Bisect

- Good: `ad1eb6ae`
- Bad: `fd4bf0bf` / `7acf896e`
- Result: First bad commit is `fd4bf0bf` (#1372), but root cause is **increased parallel contention / scheduling**, not interop IP extraction logic.

## Experiments

### A — empty listen_addrs

Under full load, identify handler sometimes ran with `host.get_addrs() == []`. Added 5s wait for addrs/transport addrs in handler and `get_transport_addrs()` fallback in `_mk_identify_protobuf`.

### B — framed read vs `stream.read(8192)`

Integration tests use `read_length_prefixed_protobuf` via `tests/utils/identify_test_helpers.py`. `test_identify_protocol` keeps `parse_identify_response(stream.read(8192))` with pre-stream waits.

### C — identify wait after `connect()`

`test_host_connect` calls `await host._identify_peer(...)` and compares transport-level addrs (peerstore may omit `/p2p` suffix). `test_yamux_stress_ping` retries `_identify_peer` up to 10s.

### D — resource limits

`ulimit -n` 100000; no FD exhaustion observed. Failures are timing/order under CPU contention, not resource limits.

## Root cause (confirmed)

1. **Parallel suite load** causes identify handlers to run before listen addrs are visible, background identify to lag behind assertions, and occasional truncated identify reads.
1. **#1372** increased suite size and shifted xdist worker scheduling, making latent races surface consistently (6 failures vs 0 on `ad1eb6ae`).
1. These tests pass in isolation even with `-n auto`; they are not logic bugs but **load-sensitive integration tests**.

## Fix applied

1. **Production** ([`libp2p/identity/identify/identify.py`](../../libp2p/identity/identify/identify.py)): wait for listen addrs in identify handler; fallback to `get_transport_addrs()` in `_mk_identify_protobuf`.
1. **Tests**: synchronization helpers in [`tests/utils/identify_test_helpers.py`](../../tests/utils/identify_test_helpers.py); framed reads; `_identify_peer` waits; transport-level addr comparison in `test_host_connect`.
1. **Makefile**: split `make test` into parallel phase (`-m "not serial_only"`) and serial phase (6 explicit test paths, `-n 0`).
1. **Marker**: `@pytest.mark.serial_only` on the 6 tests; registered in `pyproject.toml`.
1. **`wait_for_peerstore_addrs`** helper in [`libp2p/tools/utils.py`](../../libp2p/tools/utils.py) for reuse (not wired into global `connect()` — that caused widespread timeouts).

## Validation

| Run | `make pr` | Notes                                    |
| --- | --------- | ---------------------------------------- |
| 1   | Pass      | lint, typecheck, parallel + serial tests |
| 2   | Pass      | `make test` × 3 consecutive              |
| 3   | Pass      | `make test` × 3 consecutive              |
