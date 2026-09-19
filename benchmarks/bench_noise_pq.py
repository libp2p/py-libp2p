"""
Noise PQ vs classical Noise benchmarks for py-libp2p.

Measures:
  1. ML-KEM-768 KEM micro-benchmarks: keygen, encapsulate, decapsulate
  2. Classical Noise XX handshake latency (round-trip)
  3. Noise XXhfs (PQ) handshake latency (round-trip)
  4. Post-handshake transport throughput: 1 KB, 10 KB, 100 KB

All latencies are median over N_HANDSHAKES iterations.
Throughput is measured as MB/s sustained over N_THROUGHPUT rounds.

Run:
    cd py-libp2p
    python benchmarks/bench_noise_pq.py
"""

import math
from pathlib import Path
import statistics
import time

import trio

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

N_WARMUP = 3  # warm-up rounds discarded before measurement
N_HANDSHAKES = 50  # handshake latency iterations
N_THROUGHPUT = 200  # throughput iterations per message size
N_KEM = 200  # KEM micro-benchmark iterations

# Human-readable names for the IKem implementations, so a printed number is
# always attributable to a backend.
_BACKEND_NAMES = {
    "MLKEM768NativeKem": "cryptography (native)",
    "MLKEM768Kem": "kyber-py (pure Python)",
}

# ---------------------------------------------------------------------------
# In-memory connection (same as test helpers)
# ---------------------------------------------------------------------------


class _MemoryConn:
    def __init__(self, send_chan, recv_chan) -> None:
        self._send = send_chan
        self._recv = recv_chan
        self._buf = bytearray()

    async def read(self, n: int | None = None) -> bytes:
        while not self._buf:
            try:
                chunk = await self._recv.receive()
            except trio.EndOfChannel:
                return b""
            self._buf.extend(chunk)
        if n is None:
            data = bytes(self._buf)
            self._buf.clear()
            return data
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    async def write(self, data: bytes) -> None:
        await self._send.send(bytes(data))

    async def close(self) -> None:
        await self._send.aclose()

    def get_remote_address(self) -> None:
        return None

    def get_transport_addresses(self) -> list:
        return []

    def get_connection_type(self):
        from libp2p.connection_types import ConnectionType

        return ConnectionType.UNKNOWN


def _make_conn_pair() -> tuple[_MemoryConn, _MemoryConn]:
    a_to_b_s, a_to_b_r = trio.open_memory_channel(math.inf)
    b_to_a_s, b_to_a_r = trio.open_memory_channel(math.inf)
    return _MemoryConn(a_to_b_s, b_to_a_r), _MemoryConn(b_to_a_s, a_to_b_r)


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------


def _make_pq_pair():
    """Return (transport_local, peer_remote, transport_remote)."""
    from libp2p.crypto.ed25519 import create_new_key_pair
    from libp2p.crypto.keys import KeyPair
    from libp2p.crypto.x25519 import X25519PrivateKey
    from libp2p.peer.id import ID
    from libp2p.security.noise.pq.transport_pq import TransportPQ

    kp_l = create_new_key_pair()
    kp_r = create_new_key_pair()
    t_l = TransportPQ(
        KeyPair(kp_l.private_key, kp_l.public_key), X25519PrivateKey.new()
    )
    t_r = TransportPQ(
        KeyPair(kp_r.private_key, kp_r.public_key), X25519PrivateKey.new()
    )
    peer_r = ID.from_pubkey(kp_r.public_key)
    return t_l, peer_r, t_r


def _make_classical_pair():
    """Return (transport_local, peer_remote, transport_remote)."""
    from libp2p.crypto.ed25519 import create_new_key_pair
    from libp2p.crypto.keys import KeyPair
    from libp2p.crypto.x25519 import X25519PrivateKey
    from libp2p.peer.id import ID
    from libp2p.security.noise.transport import Transport

    kp_l = create_new_key_pair()
    kp_r = create_new_key_pair()
    t_l = Transport(KeyPair(kp_l.private_key, kp_l.public_key), X25519PrivateKey.new())
    t_r = Transport(KeyPair(kp_r.private_key, kp_r.public_key), X25519PrivateKey.new())
    peer_r = ID.from_pubkey(kp_r.public_key)
    return t_l, peer_r, t_r


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------


def _fmt(ms: float, ops_s: float) -> str:
    return f"{ms:7.2f} ms/op  ({ops_s:8.1f} ops/s)"


def _stats(samples_s: list[float]) -> tuple[float, float]:
    """Return (median_ms, ops_per_sec) from list of elapsed seconds."""
    med_ms = statistics.median(samples_s) * 1000
    ops_s = 1.0 / statistics.median(samples_s)
    return med_ms, ops_s


# ---------------------------------------------------------------------------
# 1. KEM micro-benchmarks (synchronous, no trio needed)
# ---------------------------------------------------------------------------


def _bench_one_kem(kem, n_warmup: int | None = None, n_iter: int | None = None) -> dict:
    """Run keygen/encap/decap micro-benchmarks for any IKem backend."""
    n_warmup = N_WARMUP if n_warmup is None else n_warmup
    n_iter = N_KEM if n_iter is None else n_iter

    for _ in range(n_warmup):
        kem.keygen()
    samples: list[float] = []
    for _ in range(n_iter):
        t0 = time.perf_counter()
        pk, sk = kem.keygen()
        samples.append(time.perf_counter() - t0)
    keygen_ms, keygen_ops = _stats(samples)

    pk, sk = kem.keygen()
    for _ in range(n_warmup):
        kem.encapsulate(pk)
    samples = []
    for _ in range(n_iter):
        t0 = time.perf_counter()
        ct, ss = kem.encapsulate(pk)
        samples.append(time.perf_counter() - t0)
    encap_ms, encap_ops = _stats(samples)

    ct, _ = kem.encapsulate(pk)
    for _ in range(n_warmup):
        kem.decapsulate(ct, sk)
    samples = []
    for _ in range(n_iter):
        t0 = time.perf_counter()
        kem.decapsulate(ct, sk)
        samples.append(time.perf_counter() - t0)
    decap_ms, decap_ops = _stats(samples)

    return {
        "keygen_ms": keygen_ms,
        "keygen_ops": keygen_ops,
        "encap_ms": encap_ms,
        "encap_ops": encap_ops,
        "decap_ms": decap_ms,
        "decap_ops": decap_ops,
    }


def bench_kem() -> dict:
    """
    Benchmark the backend a handshake would actually pick.

    The result carries the backend's name under ``"backend"``: the numbers
    are meaningless without it, since the two backends differ by more than an
    order of magnitude on keygen.
    """
    from libp2p.security.noise.pq.kem_backends import make_fast_kem

    kem = make_fast_kem()
    name = _BACKEND_NAMES.get(type(kem).__name__, type(kem).__name__)
    print(f"  Benchmarking the selected backend: {name}…")
    return {"backend": name, **_bench_one_kem(kem)}


def bench_kem_backends() -> dict:
    """
    Compare available KEM backends.

    Returns a dict keyed by backend name, each value is a _bench_one_kem dict.
    The native backend is skipped when this build of cryptography has no
    ML-KEM support, which is the same condition make_fast_kem() falls back on.
    """
    from libp2p.security.noise.pq.kem import MLKEM768Kem, MLKEM768NativeKem

    results = {}
    try:
        native = MLKEM768NativeKem()
    except Exception as exc:
        print(f"  Skipping native backend: {exc}")
    else:
        print("  Benchmarking cryptography (native)…")
        results["cryptography (native)"] = _bench_one_kem(native)

    print("  Benchmarking kyber-py (pure Python)…")
    results["kyber-py"] = _bench_one_kem(MLKEM768Kem())
    return results


# ---------------------------------------------------------------------------
# 2. Handshake latency benchmarks (async)
# ---------------------------------------------------------------------------


async def _one_pq_handshake(t_l, peer_r, t_r) -> float:
    conn_l, conn_r = _make_conn_pair()
    t0 = time.perf_counter()
    async with trio.open_nursery() as n:
        n.start_soon(t_l.secure_outbound, conn_l, peer_r)
        n.start_soon(t_r.secure_inbound, conn_r)
    return time.perf_counter() - t0


async def _one_classical_handshake(t_l, peer_r, t_r) -> float:
    conn_l, conn_r = _make_conn_pair()
    t0 = time.perf_counter()
    async with trio.open_nursery() as n:
        n.start_soon(t_l.secure_outbound, conn_l, peer_r)
        n.start_soon(t_r.secure_inbound, conn_r)
    return time.perf_counter() - t0


async def bench_handshakes() -> dict:
    for _ in range(N_WARMUP):
        await _one_classical_handshake(*_make_classical_pair())
        await _one_pq_handshake(*_make_pq_pair())

    samples_classical: list[float] = []
    samples_pq: list[float] = []
    ratios: list[float] = []
    for i in range(N_HANDSHAKES):
        # Interleave the two protocols and alternate which goes first, so
        # machine drift is largely common-mode and its effect on the
        # per-iteration ratio is largely (not fully) cancelled.
        if i % 2 == 0:
            c = await _one_classical_handshake(*_make_classical_pair())
            p = await _one_pq_handshake(*_make_pq_pair())
        else:
            p = await _one_pq_handshake(*_make_pq_pair())
            c = await _one_classical_handshake(*_make_classical_pair())
        samples_classical.append(c)
        samples_pq.append(p)
        ratios.append(p / c)

    xx_ms, xx_ops = _stats(samples_classical)
    xxhfs_ms, xxhfs_ops = _stats(samples_pq)
    return {
        "xx_ms": xx_ms,
        "xx_ops": xx_ops,
        "xxhfs_ms": xxhfs_ms,
        "xxhfs_ops": xxhfs_ops,
        "overhead_x": statistics.median(ratios),
        "overhead_min_x": min(ratios),
        "overhead_max_x": max(ratios),
    }


# ---------------------------------------------------------------------------
# 3. Transport throughput (MB/s) after handshake completes
# ---------------------------------------------------------------------------


async def _throughput_one(session_out, session_in, payload: bytes) -> float:
    t0 = time.perf_counter()
    await session_out.write(payload)
    await session_in.read(len(payload))
    return time.perf_counter() - t0


async def _bench_throughput_one_size(make_pair_fn, size: int, n_rounds: int) -> float:
    """Return throughput in MB/s for a single payload size."""
    payload = b"X" * size

    # One handshake to get the sessions
    t_l, peer_r, t_r = make_pair_fn()
    conn_l, conn_r = _make_conn_pair()
    sessions: list = [None, None]

    async def do_out() -> None:
        sessions[0] = await t_l.secure_outbound(conn_l, peer_r)

    async def do_in() -> None:
        sessions[1] = await t_r.secure_inbound(conn_r)

    async with trio.open_nursery() as n:
        n.start_soon(do_out)
        n.start_soon(do_in)

    sess_out, sess_in = sessions

    # Warm-up
    for _ in range(N_WARMUP):
        await sess_out.write(payload)
        await sess_in.read(size)

    # Timed rounds
    elapsed: list[float] = []
    for _ in range(n_rounds):
        t0 = time.perf_counter()
        await sess_out.write(payload)
        await sess_in.read(size)
        elapsed.append(time.perf_counter() - t0)

    med_s = statistics.median(elapsed)
    return (size / (1024 * 1024)) / med_s  # MB/s


async def bench_throughput() -> dict:
    # Noise spec caps single messages at 65535 bytes; 60 KB stays safely under
    # the per-frame limit of both transports (both use 2-byte length prefixes).
    sizes = [1024, 10 * 1024, 60 * 1024]
    results: dict = {"classical": {}, "pq": {}}

    for size in sizes:
        results["classical"][size] = await _bench_throughput_one_size(
            _make_classical_pair, size, N_THROUGHPUT
        )
        results["pq"][size] = await _bench_throughput_one_size(
            _make_pq_pair, size, N_THROUGHPUT
        )

    return results


# ---------------------------------------------------------------------------
# Wire-size accounting (no runtime measurement needed; pure arithmetic)
# ---------------------------------------------------------------------------


def wire_sizes() -> dict:
    from libp2p.security.noise.pq.kem import MLKEM768_CT_SIZE, MLKEM768_PK_SIZE

    x25519 = 32
    aead_tag = 16

    # Classical XX (Noise spec, no libp2p payload for size accounting)
    # Msg 1: e (32)
    # Msg 2: e (32) + enc_s (48) + enc_payload (variable, use 0 here)
    # Msg 3: enc_s (48) + enc_payload (variable)
    classical_fixed = 32 + (32 + 48) + 48  # = 160 B fixed; payload adds ~32+ per side

    # XXhfs
    # Msg A: e_pk (32) + e1_pk (1184)                                   = 1216
    # Msg B: e (32) + enc_ct (1088+16=1104) + enc_s (48) + enc_payload
    # Msg C: enc_s (48) + enc_payload
    msg_a = x25519 + MLKEM768_PK_SIZE  # 32 + 1184 = 1216
    msg_b_fixed = x25519 + (MLKEM768_CT_SIZE + aead_tag) + (x25519 + aead_tag)  # 1200
    msg_c_fixed = x25519 + aead_tag  # 48

    return {
        "classical_msg1": 32,
        "classical_msg2_fixed": 32 + 48,
        "classical_msg3_fixed": 48,
        "xxhfs_msg_a": msg_a,
        "xxhfs_msg_b_fixed": msg_b_fixed,
        "xxhfs_msg_c_fixed": msg_c_fixed,
        "xxhfs_total_fixed": msg_a + msg_b_fixed + msg_c_fixed,
        "classical_total_fixed": classical_fixed,
    }


# ---------------------------------------------------------------------------
# Main entry point + pretty-print results
# ---------------------------------------------------------------------------


def print_section(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


async def run_all() -> dict:
    print("Running benchmarks … (this may take ~30–60 seconds)")
    print(f"  KEM iterations:       {N_KEM}")
    print(f"  Handshake iterations: {N_HANDSHAKES}")
    print(f"  Throughput rounds:    {N_THROUGHPUT}")

    kem = bench_kem()
    backends = bench_kem_backends()
    handshakes = await bench_handshakes()
    throughput = await bench_throughput()
    wires = wire_sizes()

    # ---- print ----

    print_section("ML-KEM-768 KEM backend comparison")
    header = (
        f"  {'Backend':<20} {'keygen':>10} {'encap':>10} {'decap':>10} {'speedup':>10}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    baseline_keygen = backends["kyber-py"]["keygen_ms"]
    for name, b in backends.items():
        speedup = (
            baseline_keygen / b["keygen_ms"] if b["keygen_ms"] > 0 else float("inf")
        )
        print(
            f"  {name:<20} {b['keygen_ms']:>9.2f}ms"
            f" {b['encap_ms']:>9.2f}ms"
            f" {b['decap_ms']:>9.2f}ms"
            f"  {speedup:>6.1f}x"
        )

    print_section(
        f"ML-KEM-768 KEM micro-benchmarks (make_fast_kem() selected: {kem['backend']})"
    )
    print(f"  keygen     : {_fmt(kem['keygen_ms'], kem['keygen_ops'])}")
    print(f"  encapsulate: {_fmt(kem['encap_ms'], kem['encap_ops'])}")
    print(f"  decapsulate: {_fmt(kem['decap_ms'], kem['decap_ops'])}")
    kem_round_trip = kem["encap_ms"] + kem["decap_ms"]
    print(f"  round-trip (encap+decap): {kem_round_trip:.2f} ms")

    print_section("Handshake latency (in-memory, round-trip)")
    print(f"  Classical XX : {_fmt(handshakes['xx_ms'], handshakes['xx_ops'])}")
    print(f"  XXhfs (PQ)   : {_fmt(handshakes['xxhfs_ms'], handshakes['xxhfs_ops'])}")
    print(
        f"  Overhead     : {handshakes['overhead_x']:.1f}x"
        f" (median of paired per-iteration ratios,"
        f" range {handshakes['overhead_min_x']:.1f}x"
        f"-{handshakes['overhead_max_x']:.1f}x)"
    )
    print("                 (not the ratio of the two medians printed above)")

    print_section("Transport throughput (after handshake)")
    print(f"  {'Size':>8}  {'Classical':>12}  {'XXhfs (PQ)':>12}  {'Ratio':>8}")
    for size in [1024, 10 * 1024, 60 * 1024]:
        label = f"{size // 1024} KB"
        c = throughput["classical"][size]
        p = throughput["pq"][size]
        ratio = p / c if c > 0 else float("inf")
        print(f"  {label:>8}  {c:>10.1f} MB/s  {p:>10.1f} MB/s  {ratio:>7.2f}x")

    print_section("Wire sizes (handshake bytes, excluding libp2p payload)")
    print(f"  Classical XX total (fixed): {wires['classical_total_fixed']} B")
    print(f"    Msg 1: {wires['classical_msg1']} B")
    print(f"    Msg 2: {wires['classical_msg2_fixed']} B (fixed, + payload)")
    print(f"    Msg 3: {wires['classical_msg3_fixed']} B (fixed, + payload)")
    print()
    print(f"  XXhfs total (fixed): {wires['xxhfs_total_fixed']} B")
    print(f"    Msg A: {wires['xxhfs_msg_a']} B (e + e1_pk)")
    print(f"    Msg B: {wires['xxhfs_msg_b_fixed']} B (e + enc_ct + enc_s)")
    print(f"    Msg C: {wires['xxhfs_msg_c_fixed']} B (enc_s, fixed)")
    overhead_b = wires["xxhfs_total_fixed"] - wires["classical_total_fixed"]
    overhead_x = overhead_b / wires["classical_total_fixed"]
    print(f"  Wire overhead vs classical: +{overhead_b} B ({overhead_x:.0f}x)")

    print()
    return {
        "kem": kem,
        "handshakes": handshakes,
        "throughput": throughput,
        "wire_sizes": wires,
    }


def save_results(results: dict) -> None:
    """Save a markdown results file, mirroring js-libp2p-noise/benchmarks/results.md."""
    kem = results["kem"]
    hs = results["handshakes"]
    tp = results["throughput"]
    ws = results["wire_sizes"]

    lines = [
        "# py-libp2p Noise PQ Benchmark Results",
        "",
        "> Generated by `benchmarks/bench_noise_pq.py`",
        ">",
        "> Suite: `Noise_XXhfs_25519+MLKEM768_ChaChaPoly_SHA256`",
        "> (`/noise-mlkem768-hfs/0.2.0`)",
        ">",
        f"> Iterations: KEM={N_KEM}, handshake={N_HANDSHAKES},"
        f" throughput={N_THROUGHPUT}",
        "",
        "## ML-KEM-768 KEM Micro-benchmarks",
        "",
        f"Backend measured: **{kem['backend']}** (what `make_fast_kem()`"
        " selected on this machine).",
        "",
        "| Operation | Median (ms) | Throughput (ops/s) |",
        "|-----------|-------------|--------------------|",
        f"| keygen | {kem['keygen_ms']:.2f} | {kem['keygen_ops']:.0f} |",
        f"| encapsulate | {kem['encap_ms']:.2f} | {kem['encap_ops']:.0f} |",
        f"| decapsulate | {kem['decap_ms']:.2f} | {kem['decap_ops']:.0f} |",
        f"| round-trip (encap+decap) | {kem['encap_ms'] + kem['decap_ms']:.2f} | n/a |",
        "",
        "## Handshake Latency (in-memory, round-trip)",
        "",
        "| Pattern | Median (ms) | Throughput (ops/s) |",
        "|---------|-------------|--------------------|",
        f"| Classical Noise XX | {hs['xx_ms']:.2f} | {hs['xx_ops']:.0f} |",
        f"| Noise XXhfs (ML-KEM-768) | {hs['xxhfs_ms']:.2f} | {hs['xxhfs_ops']:.0f} |",
        f"| Overhead | {hs['overhead_x']:.1f}x | n/a |",
        "",
        (
            f"Overhead is the median of paired per-iteration ratios"
            f" (range {hs['overhead_min_x']:.1f}x-{hs['overhead_max_x']:.1f}x),"
            " not the ratio of the two medians in the rows above, so it need"
            " not equal their quotient. The samples were taken"
            " with the two protocols interleaved per iteration and"
            " alternating which goes first, so machine drift is largely"
            " common-mode and its effect on the ratio is largely (not fully)"
            " cancelled."
        ),
        "",
        "## Transport Throughput (post-handshake)",
        "",
        "| Payload | Classical (MB/s) | XXhfs (MB/s) | Ratio |",
        "|---------|-----------------|--------------|-------|",
    ]
    for size in [1024, 10 * 1024, 60 * 1024]:
        label = f"{size // 1024} KB"
        c = tp["classical"][size]
        p = tp["pq"][size]
        ratio = p / c if c > 0 else float("inf")
        lines.append(f"| {label} | {c:.1f} | {p:.1f} | {ratio:.2f}x |")

    overhead_b = ws["xxhfs_total_fixed"] - ws["classical_total_fixed"]
    lines += [
        "",
        "## Wire Sizes (fixed handshake bytes, excluding libp2p payload)",
        "",
        "| Pattern | Msg 1 | Msg 2 | Msg 3 | Total |",
        "|---------|-------|-------|-------|-------|",
        (
            f"| Classical XX | {ws['classical_msg1']} B"
            f" | {ws['classical_msg2_fixed']} B + payload"
            f" | {ws['classical_msg3_fixed']} B + payload"
            f" | {ws['classical_total_fixed']} B |"
        ),
        (
            f"| XXhfs | {ws['xxhfs_msg_a']} B"
            f" | {ws['xxhfs_msg_b_fixed']} B + payload"
            f" | {ws['xxhfs_msg_c_fixed']} B + payload"
            f" | {ws['xxhfs_total_fixed']} B |"
        ),
        "",
        (
            f"KEM ciphertext overhead vs classical:"
            f" +{overhead_b} B"
            f" (+{overhead_b / ws['classical_total_fixed']:.0f}x fixed bytes)"
        ),
        "",
        (
            "Cross-language comparisons (js-libp2p, Nim, Rust) live in the"
            " pq-noise-artifacts SUMMARY, not in this per-language file, since"
            " absolute milliseconds are not comparable across harnesses with"
            " different transports."
        ),
        "",
    ]

    out_path = Path(__file__).parent / "results.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    results = trio.run(run_all)
    save_results(results)
