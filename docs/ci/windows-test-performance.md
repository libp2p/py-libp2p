# Windows CI Test Performance: Analysis and Optimization Proposal

This document profiles why Windows `core` tox jobs take ~2× longer than Linux on the
same Python version, and proposes phased CI and test-suite improvements.

**Reference run:** [GitHub Actions #5174](https://github.com/libp2p/py-libp2p/actions/runs/33280982216) (PR #1462)

| Job                    | Platform | Python | Pytest wall time | Job total |
| ---------------------- | -------- | ------ | ---------------- | --------- |
| `tox (3.13, core)`     | Linux    | 3.13   | 12m 48s (768s)   | ~13m 32s  |
| `windows (3.13, core)` | Windows  | 3.13   | 28m 22s (1702s)  | ~29m 50s  |

Both jobs run the same command (`pytest -n auto --timeout=1200 tests/core`), collect
~3175 tests, and use **2 xdist workers** (`-n auto` on 2-vCPU GitHub runners).

______________________________________________________________________

## Executive summary

Windows slowness is **not** caused by fewer parallel workers or a different test set.
It comes from:

1. **Baseline Windows runner overhead** (~2× on I/O, pip, process spawn).
1. **Pubsub/gossipsub integration tests** that spin up real TCP hosts and wait on
   `trio.sleep()` — disproportionately slow on Windows localhost networking.
1. **Accidental RSA key generation in “unit” tests** — `IDFactory()` generates a full
   RSA-2048 key per fake peer ID; this dominates tests like `test_gossip_heartbeat[4]`
   and is ~4–5× slower on Windows than Linux.

Reproduce locally:

```bash
source venv/bin/activate
python scripts/ci/profile_pubsub_tests.py
python scripts/ci/profile_pubsub_tests.py --cprofile 'tests/core/pubsub/test_gossipsub.py::test_gossip_heartbeat[4]'
```

______________________________________________________________________

## Profiling: `test_gossip_heartbeat[4]`

This test looks like a fast unit test (monkeypatched router state, no multi-node mesh),
but CI timings show otherwise:

| Environment                      | `test_gossip_heartbeat[4]` |
| -------------------------------- | -------------------------- |
| Linux CI                         | 7.0s                       |
| Windows CI                       | 34.4s                      |
| Local Linux (this investigation) | 6.8–10.8s                  |

### cProfile breakdown (local Linux)

```
7.754s  test_gossip_heartbeat
7.742s  default_key_pair_factory → generate_new_rsa_identity (29 calls)
0.301s  HostFactory.create_batch_and_listen (1 host)
```

The test builds fake peers with:

```python
fake_peer_ids = [IDFactory() for _ in range(28)]
```

`IDFactory` uses `default_key_pair_factory()` → `generate_new_rsa_identity()` (RSA-2048
via PyCryptodome). That is **28 RSA key generations per parametrized case**, plus one
for the real host — **29 total**.

### Identity generation benchmark (local Linux)

| Method                                 | 28 IDs  |
| -------------------------------------- | ------- |
| `IDFactory()` (RSA)                    | ~6.3s   |
| `generate_new_rsa_identity()` × 28     | ~8.8s   |
| `generate_new_ed25519_identity()` × 28 | ~0.001s |

**Conclusion:** ~99% of this “unit” test is RSA key generation, not gossipsub logic.
Windows amplifies RSA cost further (observed ~4.9× vs Linux CI for the same test).

### Recommended test fix (high impact, low risk)

For tests that only need distinct peer IDs (not RSA-specific behavior):

- Add `FakeIDFactory` using Ed25519 or pre-generated static IDs in `tests/utils/factories.py`.
- Replace `[IDFactory() for _ in range(n)]` in gossipsub heartbeat tests and similar
  pure-logic tests.

Expected savings: **~25–30s per Windows `core` job** from gossipsub heartbeat/mesh
tests alone, plus similar gains on Linux.

______________________________________________________________________

## Profiling: multi-node integration tests

Tests like `test_fanout` and `test_fanout_maintenance` create **10 gossipsub hosts**,
connect them over TCP, and use fixed sleeps for mesh formation:

```python
await trio.sleep(2)       # mesh warmup
await trio.sleep(0.5)     # per message × 5
```

| Test                      | Linux CI | Windows CI | Local Linux |
| ------------------------- | -------- | ---------- | ----------- |
| `test_fanout_maintenance` | 26.0s    | 35.8s      | 25.1s       |
| `test_fanout`             | 21.8s    | 29.2s      | 20.3s       |

These scale with:

- RSA identity generation per host (10× per test)
- TCP listen/connect on Windows localhost
- Trio timer / scheduler granularity on Windows
- Real pubsub heartbeat background tasks

Top-40 slow test time in **pubsub** category alone: **625s (Windows)** vs **276s (Linux)**.

______________________________________________________________________

## Other contributing factors

| Factor        | Notes                                                                         |
| ------------- | ----------------------------------------------------------------------------- |
| Tox/pip setup | Windows 38s vs Linux 18s setup; pip install ~50s vs ~14s                      |
| Crypto deps   | Windows lacks `fastecdsa` (uses `coincurve` only)                             |
| Skipped tests | Windows skips `test_yamux_accept_stream_unblocks_on_error`; negligible impact |
| Job timeout   | 60 minutes — Windows uses ~50% for `core` alone                               |
| xdist workers | Both platforms: 2 workers — not a differentiator                              |

______________________________________________________________________

## CI optimization proposal

### Phase 1 — Quick CI wins (no test logic changes)

**Goal:** shave 2–5 minutes off Windows jobs without reducing coverage.

1. **Cache tox environments on Windows** (`.tox` + uv/pip cache keyed on
   `pyproject.toml` / `tox.ini` hashes). Linux interop already caches Nim; Windows
   has no dependency cache today.

1. **Use `actions/setup-python` pip cache** on Windows (and Linux for consistency):

   ```yaml
   - uses: actions/setup-python@v5
     with:
       python-version: ${{ matrix.python-version }}
       cache: pip
       cache-dependency-path: |
         pyproject.toml
         tox.ini
   ```

1. **Run `tox` without `-r` on Windows** when the tox env already exists from cache
   (keep `-r` on dependency file changes via cache key invalidation).

1. **Reduce Windows Python matrix for `core`** to a single version (e.g. 3.13 only)
   if parity with 3.11/3.12 is covered by Linux. Current Windows `core` runs 3 jobs
   × ~30m each ≈ **90m of serial runner time per PR**.

   | Current                          | Proposed (option A)              |
   | -------------------------------- | -------------------------------- |
   | 3.11, 3.12, 3.13 × core          | 3.13 × core only                 |
   | demos, utils, wheel × 3 versions | unchanged or 3.13-only for utils |

**Estimated Phase 1 savings:** 5–10 min per Windows `core` job (cache) + 60m less
total runner time if matrix is trimmed (2 fewer Python versions × 4 toxenvs).

### Phase 2 — Test suite optimizations (largest pytest savings)

**Goal:** cut Windows `core` pytest time from ~28m toward ~15–18m.

1. **`FakeIDFactory` / Ed25519 test IDs** (see profiling above).

1. **Use Ed25519 for default test host keys** where RSA is not under test:

   ```python
   # tests/utils/factories.py — consider switching default_key_pair_factory
   def default_key_pair_factory() -> KeyPair:
       return generate_new_ed25519_identity()
   ```

   Evaluate impact on tests that assert RSA-specific behavior before merging.

1. **Replace fixed `trio.sleep()` with event-driven waits** in pubsub tests where
   possible (poll mesh membership / message delivery with short timeouts).

1. **Mark slow integration tests** with `@pytest.mark.slow` and run full pubsub
   integration only on Linux; Windows runs smoke subset:

   ```ini
   # tox.ini — Windows core env
   [testenv:py313-core-windows-smoke]
   commands = pytest -n auto --timeout=1200 -m "not slow" tests/core
   ```

### Phase 3 — Structural CI changes (optional)

1. **Nightly full Windows core** on `main`; PR Windows jobs run Phase 1 + smoke only.
1. **Self-hosted Windows runner** if sub-15m Windows feedback is required (GitHub
   hosted `windows-latest` is consistently ~2× slower than Ubuntu for I/O-heavy workloads).
1. **Upload `--durations=40` as CI artifact** on every `core` job for regression tracking.

______________________________________________________________________

## Suggested implementation order

| Priority | Item                                     | Effort | Impact                    |
| -------- | ---------------------------------------- | ------ | ------------------------- |
| P0       | Document + profile script (this doc)     | Done   | Visibility                |
| P1       | pip/tox cache on Windows                 | Small  | Medium                    |
| P1       | Trim Windows Python matrix for `core`    | Small  | High (runner minutes)     |
| P2       | `FakeIDFactory` for gossipsub unit tests | Medium | High (pytest time)        |
| P2       | Ed25519 default test identities          | Medium | High (suite-wide)         |
| P3       | Windows smoke / Linux full split         | Medium | High (Windows PR latency) |

______________________________________________________________________

## Validation checklist

After each change, compare against baseline using the same metrics:

```bash
# Local
python scripts/ci/profile_pubsub_tests.py

# Full core (match CI)
pytest -n auto --timeout=1200 --durations=40 tests/core
```

Track: total pytest seconds, top-40 pubsub duration sum, Windows job wall time.

______________________________________________________________________

## References

- Workflow: `.github/workflows/tox.yml` (`timeout-minutes: 60` for both jobs)
- Pytest per-test timeout: `tox.ini` (`--timeout=1200`)
- Slow test factories: `tests/utils/factories.py` (`IDFactory`, `PubsubFactory`)
- Gossipsub heartbeat tests: `tests/core/pubsub/test_gossipsub.py`
