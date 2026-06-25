#!/usr/bin/env python3
"""
Benchmark: Issue #391 — can_dial() pre-filter in Swarm.dial_peer()

The bug: when the peerstore contained multiaddrs that the registered transport
cannot handle (e.g. UDP/QUIC addresses when only TCP is registered), the old
code called transport.dial() for each address anyway and crashed with an
unhandled ProtocolLookupError.

The fix: add can_dial() to ITransport, implement it in TCP, and filter
addresses in dial_peer() before any transport call.

This benchmark quantifies the improvement on three dimensions:

  [1] can_dial() overhead   — cost of the new guard (microseconds)
  [2] Single transport.dial() attempt with a bad addr — what the old code did
      for each address before raising ProtocolLookupError
  [3] High-level dial_peer() comparison:
        BEFORE (patched, no retries): goes into transport, raises OpenConnectionError
        AFTER  (normal):              can_dial() rejects immediately → SwarmException

All async benchmarks run with retry_config.max_retries=0 to avoid sleep delays
that would dominate wall time and obscure the filter's actual contribution.
"""
import statistics
import time
from unittest.mock import patch

import trio
from multiaddr import Multiaddr

from libp2p import generate_new_ed25519_identity, new_swarm
from libp2p.network.config import RetryConfig
from libp2p.network.exceptions import SwarmException
from libp2p.peer.id import ID
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.tcp.tcp import TCP

TCP_ADDR = Multiaddr("/ip4/127.0.0.1/tcp/9000")
UDP_ADDR = Multiaddr("/ip4/127.0.0.1/udp/9090")
QUIC_ADDR = Multiaddr("/ip4/127.0.0.1/udp/9090/quic")

N_SYNC = 50_000
N_ASYNC = 3_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stats(times: list[float]) -> dict[str, float]:
    s = sorted(times)
    return {
        "mean_us": statistics.mean(s) * 1e6,
        "p50_us":  s[len(s) // 2] * 1e6,
        "p99_us":  s[int(len(s) * 0.99)] * 1e6,
        "min_us":  s[0] * 1e6,
    }


def _row(label: str, st: dict[str, float]) -> None:
    print(f"  {label}")
    print(f"    mean={st['mean_us']:.1f} µs  p50={st['p50_us']:.1f} µs  "
          f"p99={st['p99_us']:.1f} µs  min={st['min_us']:.1f} µs")


def _sep(title: str, n: int = 0) -> None:
    tag = f"  N={n:,}" if n else ""
    print(f"\n{'='*60}")
    print(f"  {title}{tag}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# [1] Synchronous can_dial() microbenchmark
# ---------------------------------------------------------------------------

def bench_can_dial() -> None:
    _sep("can_dial() overhead", N_SYNC)
    transport = TCP()

    for addr, label in [
        (TCP_ADDR,  "can_dial(tcp)   → True  (passes through)"),
        (UDP_ADDR,  "can_dial(udp)   → False (rejected)"),
        (QUIC_ADDR, "can_dial(quic)  → False (rejected)"),
    ]:
        times = []
        for _ in range(N_SYNC):
            t0 = time.perf_counter()
            transport.can_dial(addr)
            times.append(time.perf_counter() - t0)
        _row(label, _stats(times))

    udp_mean = statistics.mean(
        [time.perf_counter() - time.perf_counter() for _ in range(N_SYNC)]  # warm loop
    )
    # re-measure cleanly
    times = []
    for _ in range(N_SYNC):
        t0 = time.perf_counter()
        transport.can_dial(UDP_ADDR)
        times.append(time.perf_counter() - t0)
    overhead = statistics.mean(times) * 1e6
    print(f"\n  The guard costs ≈{overhead:.0f} µs per address."
          f"  A TCP handshake costs ≈1–100 ms → overhead is negligible.")


# ---------------------------------------------------------------------------
# [2] transport.dial() with bad addr (single attempt, no retry)
#     This is what each loop iteration did in the old code.
# ---------------------------------------------------------------------------

async def bench_transport_dial_bad_addr(n: int) -> list[float]:
    """Time a single transport.dial() call with an unsupported multiaddr."""
    transport = TCP()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            await transport.dial(UDP_ADDR)
        except OpenConnectionError:
            pass
        except Exception:
            pass
        times.append(time.perf_counter() - t0)
    return times


# ---------------------------------------------------------------------------
# [3] High-level dial_peer() comparison (max_retries=0 to avoid sleep)
# ---------------------------------------------------------------------------

def _no_retry_config() -> RetryConfig:
    return RetryConfig(max_retries=0, initial_delay=0.0, max_delay=0.0)


async def bench_before(n: int) -> list[float]:
    """
    BEFORE: dial_peer() with can_dial bypassed (returns True for all addrs).
    Goes into transport.dial() for each bad addr, raises SwarmException.
    max_retries=0 so no sleep delay between attempts.
    """
    swarm = new_swarm()
    swarm.retry_config = _no_retry_config()
    peer_id = ID.from_pubkey(generate_new_ed25519_identity().public_key)
    swarm.peerstore.add_addrs(peer_id, [UDP_ADDR, QUIC_ADDR], ttl=3600)

    times = []
    with patch.object(TCP, "can_dial", return_value=True):
        for _ in range(n):
            t0 = time.perf_counter()
            try:
                await swarm.dial_peer(peer_id)
            except SwarmException:
                pass
            except Exception:
                pass
            times.append(time.perf_counter() - t0)
    return times


async def bench_after(n: int) -> list[float]:
    """
    AFTER: dial_peer() with can_dial() filter active.
    Rejects bad addrs before any transport call → SwarmException immediately.
    """
    swarm = new_swarm()
    swarm.retry_config = _no_retry_config()
    peer_id = ID.from_pubkey(generate_new_ed25519_identity().public_key)
    swarm.peerstore.add_addrs(peer_id, [UDP_ADDR, QUIC_ADDR], ttl=3600)

    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            await swarm.dial_peer(peer_id)
        except SwarmException:
            pass
        times.append(time.perf_counter() - t0)
    return times


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    # [1] Synchronous can_dial()
    bench_can_dial()

    # [2] Single transport.dial() with bad addr
    _sep("BEFORE path: transport.dial(bad_addr) — single attempt", N_ASYNC)
    print("  (what the old code did for each unsupported addr; no retry)")
    dial_times = await bench_transport_dial_bad_addr(N_ASYNC)
    _row("transport.dial(udp_addr) → OpenConnectionError", _stats(dial_times))

    # [3] High-level comparison
    _sep("BEFORE fix — dial_peer() no filter, max_retries=0", N_ASYNC)
    before = await bench_before(N_ASYNC)
    _row("dial_peer(bad_addrs) before  ", _stats(before))

    _sep("AFTER fix  — dial_peer() with can_dial() filter", N_ASYNC)
    after = await bench_after(N_ASYNC)
    _row("dial_peer(bad_addrs) after   ", _stats(after))

    # Summary
    mean_before = statistics.mean(before)
    mean_after  = statistics.mean(after)
    mean_dial   = statistics.mean(dial_times)

    speedup      = mean_before / mean_after
    saving_us    = (mean_before - mean_after) * 1e6
    dial_ratio   = mean_dial / (statistics.mean(after) / len([UDP_ADDR, QUIC_ADDR]))

    print(f"\n{'='*60}")
    print(f"  Results Summary")
    print(f"  ---------------")
    print(f"  Before  (no filter, no retry):  {mean_before*1e6:.1f} µs/call")
    print(f"  After   (can_dial() filter):     {mean_after*1e6:.1f} µs/call")
    print(f"  Speedup: {speedup:.1f}x   saving ≈{saving_us:.1f} µs per bad-addr dial")
    print(f"")
    print(f"  Error type BEFORE: SwarmException wrapping OpenConnectionError")
    print(f"                     (came from ProtocolLookupError — wrong layer)")
    print(f"  Error type AFTER:  SwarmException('No supported transport ...')")
    print(f"                     (descriptive, raised at the right abstraction)")
    print(f"  Note: in production max_retries>0 amplifies the before-fix cost by")
    print(f"        retry_count × sleep_delay per unsupported address.")
    print(f"{'='*60}")


if __name__ == "__main__":
    print("py-libp2p  ·  Issue #391 Benchmark")
    print("TCP Swarm: can_dial() pre-filter impact")
    print()
    trio.run(main)
    print("\nDone.")
