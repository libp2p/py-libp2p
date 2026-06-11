#!/usr/bin/env python3
# p2pcalc/main.py — P2PCalc entrypoint
# Author: Dashpreet Singh <dashpreetsinghhanda@gmail.com>
#
# Usage:
#   # Start a node, join room "my-sheet"
#   python -m p2pcalc.main --room my-sheet --port 4001
#
#   # Second peer, connecting to first
#   python -m p2pcalc.main --room my-sheet --port 4002 \
#     --peer /ip4/127.0.0.1/tcp/4001/p2p/<peer_id>
#
#   # Multiple rooms on one node
#   python -m p2pcalc.main --room room1 --room room2 --port 4001

import argparse
import asyncio
import json
import logging
import signal
import sys

from .adapter import AdapterManager
from .crdt import ConflictPolicy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("p2pcalc")


async def run(args: argparse.Namespace) -> None:
    policy_map = {
        "lww": ConflictPolicy.LAST_WRITE_WINS,
        "mvr": ConflictPolicy.MULTI_VALUE,
        "peer": ConflictPolicy.PEER_PRIORITY,
    }
    policy = policy_map.get(args.conflict_policy, ConflictPolicy.MULTI_VALUE)

    manager = AdapterManager(
        redis_url=args.redis,
        p2p_port=args.port,
        known_peers=args.peer or [],
        conflict_policy=policy,
    )

    peer_id = await manager.start()
    print("\nP2PCalc node started")
    print(f"Peer ID : {peer_id}")
    print(f"Addrs   : {manager._node.get_listen_addrs()}")
    print(f"Redis   : {args.redis}")
    print(f"Policy  : {policy.value}")

    for room in args.room:
        await manager.add_room(room)
        print(f"Room    : {room} (topic=p2pcalc/{room})")

    print("\nReady. Ctrl-C to stop.\n")

    # Periodic stats logging
    async def stats_loop() -> None:
        while True:
            await asyncio.sleep(30)
            stats = manager.all_stats()
            logger.info("Stats: %s", json.dumps(stats, indent=2))

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        print("\nShutting down...")
        stop_event.set()

    # asyncio.loop.add_signal_handler is not available on Windows;
    # fall back to the stdlib signal module which works on all platforms.
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    else:
        signal.signal(signal.SIGINT, lambda _s, _f: _signal_handler())
        signal.signal(signal.SIGTERM, lambda _s, _f: _signal_handler())

    stats_task = asyncio.create_task(stats_loop())

    await stop_event.wait()

    stats_task.cancel()
    await manager.stop()
    print("Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="P2PCalc — Decentralised EtherCalc via py-libp2p GossipSub"
    )
    parser.add_argument(
        "--room",
        "-r",
        action="append",
        default=[],
        metavar="ROOM_NAME",
        help="EtherCalc room name(s) to bridge (can repeat)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=0,
        help="TCP port for libp2p (0 = random)",
    )
    parser.add_argument(
        "--peer",
        action="append",
        default=[],
        metavar="MULTIADDR",
        help="Known peer multiaddr(s) to connect to on startup",
    )
    parser.add_argument(
        "--redis",
        default="redis://localhost:6379",
        help="Redis URL (default: redis://localhost:6379)",
    )
    parser.add_argument(
        "--conflict-policy",
        choices=["lww", "mvr", "peer"],
        default="mvr",
        help=(
            "Conflict resolution: lww=last-write-wins, "
            "mvr=multi-value (default), peer=peer-priority"
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.room:
        print("Error: at least one --room is required")
        parser.print_help()
        sys.exit(1)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
