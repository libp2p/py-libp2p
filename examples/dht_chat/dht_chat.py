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


async def run_network_size(network_size: int) -> None:
    """
    Spin up ``network_size`` in-process DHT chat peers and exercise Peer-ID lookup.

    Topology: peer 0 is the intro node; peers 1..N-1 dial peer 0 once. Then peer 1
    resolves peer N-1 via ``KadDHT.find_peer`` (no multiaddr) and sends a chat
    message.
    """
    if network_size < 2:
        raise ValueError("--network-size must be >= 2")

    print(f"=== DHT network-size experiment: N={network_size} ===")
    t0 = time.perf_counter()

    async with AsyncExitStack() as stack:
        hosts = []
        dhts: list[KadDHT] = []
        ports: list[int] = []

        for i in range(network_size):
            port = find_free_port()
            ports.append(port)
            host = new_host()
            # Loopback-only keeps large-N demos lightweight.
            listen = [Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")]
            await stack.enter_async_context(host.run(listen_addrs=listen))
            hosts.append(host)

        received = trio.Event()
        got: dict[str, bytes | None] = {"data": None}
        target_idx = network_size - 1

        async def target_handler(stream: INetStream) -> None:
            data = await stream.read(MAX_READ_LEN)
            got["data"] = data
            received.set()
            await stream.close()

        hosts[target_idx].set_stream_handler(PROTOCOL_ID, target_handler)

        for host in hosts:
            dht = KadDHT(host, DHTMode.SERVER)
            await stack.enter_async_context(background_trio_service(dht))
            dhts.append(dht)

        intro = PeerInfo(hosts[0].get_id(), hosts[0].get_addrs())
        join_limiter = trio.CapacityLimiter(min(32, network_size))

        async def join_peer(i: int) -> None:
            async with join_limiter:
                await hosts[i].connect(intro)
                await dhts[i].add_peer(hosts[0].get_id())

        t_join = time.perf_counter()
        async with trio.open_nursery() as nursery:
            for i in range(1, network_size):
                nursery.start_soon(join_peer, i)
        join_s = time.perf_counter() - t_join
        print(
            f"Joined {network_size - 1} peers to intro in {join_s:.2f}s "
            f"(intro connected={len(hosts[0].get_connected_peers())})"
        )

        # Seed intro RT with everyone currently connected.
        for peer_id in hosts[0].get_connected_peers():
            await dhts[0].add_peer(peer_id)

        # Give routing tables a moment to settle under load.
        settle_deadline = time.perf_counter() + min(30.0, 2.0 + network_size * 0.05)
        while time.perf_counter() < settle_deadline:
            for peer_id in hosts[0].get_connected_peers():
                await dhts[0].add_peer(peer_id)
            if dhts[0].get_routing_table_size() >= min(network_size - 1, 20):
                break
            await trio.sleep(0.2)

        rt_sizes = [d.get_routing_table_size() for d in dhts]
        median_rt = sorted(rt_sizes)[len(rt_sizes) // 2]
        print(
            "Routing table sizes: "
            f"intro={rt_sizes[0]} "
            f"source(peer1)={rt_sizes[1]} "
            f"target(peer{target_idx})={rt_sizes[target_idx]} "
            f"min={min(rt_sizes)} max={max(rt_sizes)} median={median_rt}"
        )

        source_host, source_dht = hosts[1], dhts[1]
        target_id = hosts[target_idx].get_id()

        t_lookup = time.perf_counter()
        found: PeerInfo | None = None
        attempts = 0
        with trio.fail_after(60):
            while True:
                attempts += 1
                found = await source_dht.find_peer(target_id)
                if found is not None and found.addrs:
                    break
                await trio.sleep(0.2)
        lookup_s = time.perf_counter() - t_lookup
        assert found is not None
        print(
            f"Peer 1 looked up peer {target_idx} via DHT in {lookup_s:.2f}s "
            f"({attempts} attempt(s), {len(found.addrs)} addr(s))"
        )

        t_msg = time.perf_counter()
        await source_host.connect(found)
        stream = await source_host.new_stream(target_id, [PROTOCOL_ID])
        payload = f"hello-from-N{network_size}\n".encode()
        try:
            await stream.write(payload)
        finally:
            await stream.close()

        with trio.fail_after(30):
            await received.wait()
        msg_s = time.perf_counter() - t_msg

        ok = got["data"] == payload
        total_s = time.perf_counter() - t0
        print(f"Chat delivery {'OK' if ok else 'FAIL'} in {msg_s:.2f}s")
        print(
            f"TOTAL N={network_size}: join={join_s:.2f}s lookup={lookup_s:.2f}s "
            f"msg={msg_s:.2f}s wall={total_s:.2f}s"
        )
        if not ok:
            raise RuntimeError(f"Unexpected payload: {got['data']!r}")


def main() -> None:
    description = """
    DHT Peer-ID chat demo (issue #880).

    Interactive mode: start one intro peer, then join others with
    --bootstrap <multiaddr>. Subsequent dials use KadDHT.find_peer(peer_id).

    Automated mode: --network-size N spins up N in-process peers, joins them
    through one intro peer, then has peer 1 look up peer N-1 by Peer ID and chat.
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
    args = parser.parse_args()

    try:
        if args.network_size is not None:
            trio.run(run_network_size, args.network_size)
        else:
            trio.run(run, args.port, args.bootstrap)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
