"""
DHT-based chat example: look up peers by Peer ID, then open a chat stream.

This demo shows how KadDHT can replace hardcoded messaging bootstrap servers
*after* peers have joined a DHT overlay. A one-time introduction (``--bootstrap``
multiaddr) is still required — an empty routing table cannot resolve Peer IDs.

Typical 3-terminal flow:

1. Start the intro peer (no ``--bootstrap``). Copy the printed bootstrap multiaddr
   and its Peer ID.
2. Start two more peers with ``--bootstrap <intro_multiaddr>``.
3. On peer B, run ``connect <peer_C_id>`` (Peer ID only — no multiaddr), then
   ``msg <peer_C_id> hello``.
"""

from __future__ import annotations

import argparse
from contextlib import (
    AsyncExitStack,
)
import logging
import random
import statistics
import sys
import time

import multiaddr
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p import (
    new_host,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.kad_dht.kad_dht import (
    DHTMode,
    KadDHT,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
    info_from_p2p_addr,
)
from libp2p.tools.anyio_service import (
    background_trio_service,
)
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
)

PROTOCOL_ID = TProtocol("/dht-chat/1.0.0")
MAX_READ_LEN = 2**16

logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

logger = logging.getLogger("dht-chat")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False


HELP_TEXT = """
Commands:
  id                         Print this peer's Peer ID
  addrs                      Print listen multiaddrs
  peers                      Print connected peers and DHT routing-table size
  lookup <peer_id>           Resolve addresses via KadDHT.find_peer (no dial)
  connect <peer_id>          Look up peer via DHT, then dial
  msg <peer_id> <text>       Send a chat message (looks up/dials if needed)
  help                       Show this help
  quit / exit                Stop the node
""".strip()


async def seed_routing_table(dht: KadDHT) -> None:
    """Add currently known peerstore peers into the DHT routing table."""
    host = dht.host
    local_id = host.get_id()
    for peer_id in host.get_peerstore().peer_ids():
        if peer_id == local_id:
            continue
        await dht.add_peer(peer_id)


async def maintain_routing_table(host, dht: KadDHT) -> None:
    """
    Periodically fold connected peers into the DHT routing table.

    The intro peer learns about joiners through host connections; without this
    loop those peers never enter the RT and FIND_NODE cannot answer lookups.
    """
    while True:
        for peer_id in host.get_connected_peers():
            await dht.add_peer(peer_id)
        await seed_routing_table(dht)
        await trio.sleep(2)


async def connect_bootstrap(host, bootstrap: str, dht: KadDHT) -> None:
    """Dial the intro peer and seed the local routing table."""
    maddr = multiaddr.Multiaddr(bootstrap)
    info = info_from_p2p_addr(maddr)
    logger.info("Connecting to intro peer %s", info.peer_id)
    await host.connect(info)
    await dht.add_peer(info.peer_id)
    await seed_routing_table(dht)
    logger.info("Joined DHT overlay via intro peer %s", info.peer_id)


async def read_incoming_chat(stream: INetStream) -> None:
    """Print messages from an inbound chat stream until it closes."""
    remote = stream.muxed_conn.peer_id
    try:
        while True:
            data = await stream.read(MAX_READ_LEN)
            if not data:
                break
            text = data.decode(errors="replace").rstrip("\n")
            print(f"\n\x1b[32m[{remote}] {text}\x1b[0m")
            print("> ", end="", flush=True)
    except Exception as exc:
        logger.debug("Inbound chat stream closed: %s", exc)
    finally:
        try:
            await stream.close()
        except Exception:
            pass


async def lookup_peer(dht: KadDHT, peer_id: ID) -> PeerInfo:
    """Resolve ``peer_id`` through the DHT and return PeerInfo with addresses."""
    logger.info("Looking up %s via KadDHT.find_peer ...", peer_id)
    found: PeerInfo | None = None
    for attempt in range(15):
        found = await dht.find_peer(peer_id)
        if found is not None and found.addrs:
            break
        await trio.sleep(0.2)
        logger.debug("find_peer attempt %s returned %s", attempt + 1, found)

    if found is None or not found.addrs:
        raise RuntimeError(
            f"DHT lookup failed for {peer_id}. "
            "Join an overlay first with --bootstrap, and ensure the target "
            "peer has also joined the same intro peer."
        )

    logger.info(
        "DHT found %s with %s addr(s)",
        found.peer_id,
        len(found.addrs),
    )
    return found


async def ensure_connected(host, dht: KadDHT, peer_id: ID) -> PeerInfo:
    """
    Resolve ``peer_id`` through the DHT (if needed) and ensure a connection.

    Returns the PeerInfo used for the dial.
    """
    if peer_id == host.get_id():
        raise ValueError("Cannot connect to self")

    if peer_id in host.get_connected_peers():
        addrs = host.get_peerstore().addrs(peer_id)
        return PeerInfo(peer_id, list(addrs))

    found = await lookup_peer(dht, peer_id)
    logger.info("Dialing %s ...", found.peer_id)
    await host.connect(found)
    await dht.add_peer(found.peer_id)
    return found


async def send_message(host, dht: KadDHT, peer_id: ID, text: str) -> None:
    """Open a chat stream to ``peer_id`` and send one line of text."""
    await ensure_connected(host, dht, peer_id)
    stream = await host.new_stream(peer_id, [PROTOCOL_ID])
    try:
        payload = text if text.endswith("\n") else text + "\n"
        await stream.write(payload.encode())
        logger.info("Sent to %s: %s", peer_id, text)
    finally:
        await stream.close()


async def command_loop(host, dht: KadDHT, nursery: trio.Nursery) -> None:
    """Read interactive commands from stdin."""
    async_stdin = trio.wrap_file(sys.stdin)
    print(HELP_TEXT)
    print("> ", end="", flush=True)

    while True:
        line = await async_stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            print("> ", end="", flush=True)
            continue

        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()

        try:
            if cmd in {"quit", "exit"}:
                logger.info("Shutting down")
                nursery.cancel_scope.cancel()
                return

            if cmd == "help":
                print(HELP_TEXT)

            elif cmd == "id":
                print(host.get_id())

            elif cmd == "addrs":
                for addr in host.get_addrs():
                    print(addr)

            elif cmd == "peers":
                connected = list(host.get_connected_peers())
                rt_size = dht.get_routing_table_size()
                print(f"connected={len(connected)} rt_size={rt_size}")
                for peer_id in connected:
                    print(f"  {peer_id}")

            elif cmd == "lookup":
                if len(parts) < 2:
                    print("usage: lookup <peer_id>")
                else:
                    peer_id = ID.from_string(parts[1])
                    info = await lookup_peer(dht, peer_id)
                    print(f"lookup ok: {info.peer_id}")
                    for addr in info.addrs:
                        print(f"  {addr}")

            elif cmd == "connect":
                if len(parts) < 2:
                    print("usage: connect <peer_id>")
                else:
                    peer_id = ID.from_string(parts[1])
                    info = await ensure_connected(host, dht, peer_id)
                    print(f"Connected to {info.peer_id}")

            elif cmd == "msg":
                if len(parts) < 3:
                    print("usage: msg <peer_id> <text>")
                else:
                    peer_id = ID.from_string(parts[1])
                    await send_message(host, dht, peer_id, parts[2])

            else:
                print(f"Unknown command: {cmd!r} (type 'help')")

        except Exception as exc:
            print(f"Error: {exc}")

        print("> ", end="", flush=True)


async def run(port: int, bootstrap: str | None) -> None:
    """Start a DHT chat node and enter the interactive command loop."""
    if port <= 0:
        port = find_free_port()

    listen_addrs = get_available_interfaces(port)
    host = new_host()

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        async def stream_handler(stream: INetStream) -> None:
            nursery.start_soon(read_incoming_chat, stream)

        host.set_stream_handler(PROTOCOL_ID, stream_handler)

        dht = KadDHT(host, DHTMode.SERVER)
        async with background_trio_service(dht):
            nursery.start_soon(maintain_routing_table, host, dht)

            if bootstrap:
                await connect_bootstrap(host, bootstrap, dht)
            else:
                logger.info(
                    "Started as intro peer (empty DHT until others --bootstrap here)"
                )

            peer_id = host.get_id()
            all_addrs = host.get_addrs()
            optimal = get_optimal_binding_address(port)
            bootstrap_maddr = f"{optimal}/p2p/{peer_id.to_string()}"

            print("\n=== DHT Chat node ready ===")
            print(f"Peer ID: {peer_id}")
            print("Listening on:")
            for addr in all_addrs:
                print(f"  {addr}")
            print("\nOther peers can join the overlay with:")
            print(f"  dht-chat-demo --bootstrap {bootstrap_maddr}")
            print(
                "\nAfter joining, use `lookup <peer_id>` / `msg <peer_id> <text>` "
                "(Peer ID only — DHT resolves addresses).\n"
            )

            await command_loop(host, dht, nursery)


async def run_network_size(
    network_size: int,
    pair_count: int | None = None,
    seed: int = 880,
) -> None:
    """
    Spin up ``network_size`` in-process DHT chat peers and run a multi-pair exam.

    Completeness: after a tree-shaped join, run ``pair_count`` random directed
    pairs ``(src -> dst)``. Each pair must ``KadDHT.find_peer(dst)`` (Peer ID
    only) and deliver a chat message. Reports success rate and latencies in ms.
    """
    if network_size < 2:
        raise ValueError("--network-size must be >= 2")

    max_pairs = network_size * (network_size - 1)
    if pair_count is None:
        # Enough random coverage to be meaningful without O(N^2) cost.
        pair_count = min(max_pairs, max(network_size, 10), 40)
    if pair_count < 1:
        raise ValueError("--pair-count must be >= 1")
    if pair_count > max_pairs:
        pair_count = max_pairs

    rng = random.Random(seed)
    print(
        f"=== DHT network-size experiment: N={network_size} "
        f"pairs={pair_count} seed={seed} ===",
        flush=True,
    )
    t0 = time.perf_counter()

    async with AsyncExitStack() as stack:
        hosts = []
        dhts: list[KadDHT] = []

        t_boot = time.perf_counter()
        for i in range(network_size):
            port = find_free_port()
            host = new_host()
            listen = [Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")]
            await stack.enter_async_context(host.run(listen_addrs=listen))
            hosts.append(host)
            if (i + 1) % 500 == 0 or i + 1 == network_size:
                print(
                    f"Started {i + 1}/{network_size} hosts "
                    f"({time.perf_counter() - t_boot:.1f}s)",
                    flush=True,
                )

        # Per-payload waiters so many peers can receive concurrent chat messages.
        pending: dict[bytes, trio.Event] = {}
        pending_lock = trio.Lock()

        def make_handler(_host_idx: int):
            async def handler(stream: INetStream) -> None:
                data = b""
                try:
                    data = await stream.read(MAX_READ_LEN)
                finally:
                    try:
                        await stream.close()
                    except Exception:
                        pass
                if not data:
                    return
                async with pending_lock:
                    event = pending.pop(data, None)
                if event is not None:
                    event.set()

            return handler

        for i, host in enumerate(hosts):
            host.set_stream_handler(PROTOCOL_ID, make_handler(i))

        for host in hosts:
            dht = KadDHT(host, DHTMode.SERVER)
            await stack.enter_async_context(background_trio_service(dht))
            dhts.append(dht)
        print(
            f"DHT services started for {network_size} peers "
            f"({time.perf_counter() - t0:.1f}s)",
            flush=True,
        )

        # Tree bootstrap: peer i dials parent (i-1)//2 (avoids star flood on root).
        join_limit = 8 if network_size >= 200 else min(16, network_size)
        join_limiter = trio.CapacityLimiter(join_limit)
        join_stats = {"ok": 0, "fail": 0}
        joined = {0}
        join_lock = trio.Lock()

        async def join_peer(i: int) -> None:
            parent = (i - 1) // 2
            parent_info = PeerInfo(hosts[parent].get_id(), hosts[parent].get_addrs())
            async with join_limiter:
                last_exc: Exception | None = None
                for attempt in range(8):
                    try:
                        await hosts[i].connect(parent_info)
                        await dhts[i].add_peer(hosts[parent].get_id())
                        await dhts[parent].add_peer(hosts[i].get_id())
                        async with join_lock:
                            join_stats["ok"] += 1
                            joined.add(i)
                        return
                    except Exception as exc:
                        last_exc = exc
                        await trio.sleep(0.05 * (attempt + 1))
                async with join_lock:
                    join_stats["fail"] += 1
                logger.warning(
                    "Join failed for peer %s (parent=%s): %s", i, parent, last_exc
                )

        t_join = time.perf_counter()
        level = [1, 2] if network_size > 2 else ([1] if network_size > 1 else [])
        level = [i for i in level if i < network_size]
        while level:
            async with trio.open_nursery() as nursery:
                for i in level:
                    nursery.start_soon(join_peer, i)
            next_level: list[int] = []
            for i in level:
                for child in (2 * i + 1, 2 * i + 2):
                    if child < network_size:
                        next_level.append(child)
            level = next_level
        join_s = time.perf_counter() - t_join
        print(
            f"Join phase done in {join_s:.2f}s: ok={join_stats['ok']} "
            f"fail={join_stats['fail']} joined={len(joined)}/{network_size}",
            flush=True,
        )
        if len(joined) < 2:
            raise RuntimeError("Need at least 2 joined peers for pair testing")

        joined_list = sorted(joined)

        # Seed RT from live connections, and push each peer's PeerInfo up the
        # tree so ancestors can answer FIND_NODE without everyone dialing root.
        t_warm = time.perf_counter()
        for i in joined_list:
            for peer_id in hosts[i].get_connected_peers():
                await dhts[i].add_peer(peer_id)

        for i in joined_list:
            if i == 0:
                continue
            info = PeerInfo(hosts[i].get_id(), hosts[i].get_addrs())
            cur = i
            while cur > 0:
                parent = (cur - 1) // 2
                try:
                    hosts[parent].get_peerstore().add_addrs(
                        info.peer_id, info.addrs, 60 * 60
                    )
                except Exception:
                    pass
                await dhts[parent].add_peer(info.peer_id, skip_server_mode_check=True)
                cur = parent

        # Bounded FIND_NODE warm toward root (best-effort record exchange).
        warm_limiter = trio.CapacityLimiter(min(8, network_size))

        async def warm_peer(i: int) -> None:
            async with warm_limiter:
                with trio.move_on_after(1.0):
                    try:
                        await dhts[i].find_peer(hosts[0].get_id())
                    except Exception:
                        pass

        async with trio.open_nursery() as nursery:
            for i in joined_list:
                if i != 0:
                    nursery.start_soon(warm_peer, i)
        warm_s = time.perf_counter() - t_warm
        print(f"Overlay warm-up done in {warm_s:.2f}s", flush=True)

        rt_sizes = [dhts[i].get_routing_table_size() for i in joined_list]
        median_rt = sorted(rt_sizes)[len(rt_sizes) // 2]
        print(
            "Routing table sizes: "
            f"min={min(rt_sizes)} max={max(rt_sizes)} median={median_rt}",
            flush=True,
        )

        # Build unique random directed pairs among joined peers.
        all_directed = [(a, b) for a in joined_list for b in joined_list if a != b]
        rng.shuffle(all_directed)
        pairs = all_directed[:pair_count]

        lookup_ms: list[float] = []
        msg_ms: list[float] = []
        pair_ok = 0
        pair_fail = 0
        lookup_budget = min(60.0, 10.0 + network_size * 0.02)

        print(f"Running {len(pairs)} lookup+chat pairs ...", flush=True)
        t_pairs = time.perf_counter()
        for idx, (src, dst) in enumerate(pairs, start=1):
            pair_succeeded = False
            last_exc: Exception | None = None
            for attempt in range(3):
                payload = f"pair-{src}-{dst}-{idx}-{seed}-a{attempt}\n".encode()
                event = trio.Event()
                async with pending_lock:
                    pending[payload] = event
                try:
                    t_lookup = time.perf_counter()
                    found: PeerInfo | None = None
                    with trio.fail_after(lookup_budget):
                        while True:
                            found = await dhts[src].find_peer(hosts[dst].get_id())
                            if found is not None and found.addrs:
                                break
                            await trio.sleep(0.1)
                    assert found is not None
                    lookup_ms.append((time.perf_counter() - t_lookup) * 1000.0)

                    t_msg = time.perf_counter()
                    await hosts[src].connect(found)
                    await dhts[src].add_peer(found.peer_id)
                    stream = await hosts[src].new_stream(found.peer_id, [PROTOCOL_ID])
                    try:
                        await stream.write(payload)
                    finally:
                        await stream.close()
                    with trio.fail_after(15):
                        await event.wait()
                    msg_ms.append((time.perf_counter() - t_msg) * 1000.0)
                    pair_succeeded = True
                    pair_ok += 1
                    break
                except Exception as exc:
                    last_exc = exc
                    async with pending_lock:
                        pending.pop(payload, None)
                    await trio.sleep(0.2 * (attempt + 1))

            if not pair_succeeded:
                pair_fail += 1
                err = (
                    f"{type(last_exc).__name__}: {last_exc}" if last_exc else "unknown"
                )
                print(
                    f"  FAIL pair {idx}/{len(pairs)} {src}->{dst}: {err}",
                    flush=True,
                )

            if idx == len(pairs) or idx % max(1, len(pairs) // 5) == 0:
                print(
                    f"  progress {idx}/{len(pairs)} ok={pair_ok} fail={pair_fail}",
                    flush=True,
                )

        pairs_s = time.perf_counter() - t_pairs
        total_s = time.perf_counter() - t0
        success_rate = 100.0 * pair_ok / len(pairs)

        def _pct(values: list[float], p: float) -> float:
            if not values:
                return float("nan")
            ordered = sorted(values)
            rank = int(round((p / 100.0) * (len(ordered) - 1)))
            return ordered[rank]

        print("=== Pair results ===", flush=True)
        print(
            f"pairs: ok={pair_ok}/{len(pairs)} fail={pair_fail} "
            f"success_rate={success_rate:.1f}% in {pairs_s:.2f}s",
            flush=True,
        )
        if lookup_ms:
            print(
                "lookup_ms: "
                f"p50={_pct(lookup_ms, 50):.1f} "
                f"p95={_pct(lookup_ms, 95):.1f} "
                f"mean={statistics.fmean(lookup_ms):.1f} "
                f"max={max(lookup_ms):.1f}",
                flush=True,
            )
        if msg_ms:
            print(
                "msg_ms: "
                f"p50={_pct(msg_ms, 50):.1f} "
                f"p95={_pct(msg_ms, 95):.1f} "
                f"mean={statistics.fmean(msg_ms):.1f} "
                f"max={max(msg_ms):.1f}",
                flush=True,
            )
        print(
            f"TOTAL N={network_size}: join={join_s:.2f}s warm={warm_s:.2f}s "
            f"pairs={pairs_s:.2f}s wall={total_s:.2f}s "
            f"join_fail={join_stats['fail']}",
            flush=True,
        )

        if pair_fail:
            raise RuntimeError(
                f"Pair battery incomplete: {pair_ok}/{len(pairs)} succeeded "
                f"({success_rate:.1f}%)"
            )
        print("COMPLETE: all lookup+chat pairs succeeded", flush=True)


def main() -> None:
    description = """
    DHT Peer-ID chat demo (issue #880).

    Interactive mode: start one intro peer, then join others with
    --bootstrap <multiaddr>. Subsequent dials use KadDHT.find_peer(peer_id).

    Automated mode: --network-size N spins up N in-process peers (tree join),
    warms the DHT, then runs random src->dst lookup+chat pairs and reports
    success rate plus lookup/msg latency in milliseconds.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-p",
        "--port",
        default=0,
        type=int,
        help="TCP listen port (0 = ephemeral); ignored with --network-size",
    )
    parser.add_argument(
        "-b",
        "--bootstrap",
        type=str,
        default=None,
        help="Intro peer multiaddr (e.g. /ip4/127.0.0.1/tcp/8000/p2p/<PeerID>)",
    )
    parser.add_argument(
        "-n",
        "--network-size",
        type=int,
        default=None,
        help="Run automated N-peer DHT overlay experiment (N >= 2) and exit",
    )
    parser.add_argument(
        "-k",
        "--pair-count",
        type=int,
        default=None,
        help="Random directed lookup+chat pairs to run (default: min(N,40))",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=880,
        help="RNG seed for pair selection (default: 880)",
    )
    args = parser.parse_args()

    try:
        if args.network_size is not None:
            trio.run(
                run_network_size,
                args.network_size,
                args.pair_count,
                args.seed,
            )
        else:
            trio.run(run, args.port, args.bootstrap)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
