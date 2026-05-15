"""
Routing Table Diagnostics — live KadDHT health inspection.

Shows how to use RoutingTableDiagnostics to get a full picture of your
node's routing table health: bucket fill rates, keyspace coverage gaps,
peer freshness, and a composite health score.

Run two terminal windows:

    # Window 1 — bootstrap node
    python examples/kademlia/routing_table_diagnostics.py --port 8888 --mode server

    # Window 2 — client node (connects to bootstrap and prints a report)
    python examples/kademlia/routing_table_diagnostics.py \
        --port 9999 --mode server --bootstrap /ip4/127.0.0.1/tcp/8888

The client node will print a full diagnostic report after a short warm-up.
"""

from __future__ import annotations

import argparse
import logging

import trio

from libp2p import new_node
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht import KadDHT
from libp2p.kad_dht.diagnostics import RoutingTableDiagnostics
from libp2p.kad_dht.kad_dht import DHTMode
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.anyio_service import background_trio_service

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


async def run(
    port: int,
    mode: str,
    bootstrap_addr: str | None,
) -> None:
    key_pair = create_new_key_pair()
    listen_addr = f"/ip4/0.0.0.0/tcp/{port}"

    async with background_trio_service(
        await new_node(key_pair=key_pair, listen_addrs=[listen_addr])
    ) as host:
        dht_mode = DHTMode.SERVER if mode == "server" else DHTMode.CLIENT
        dht = KadDHT(host, dht_mode, enable_random_walk=True)

        async with background_trio_service(dht):
            print(f"\nNode started: {host.get_id().to_base58()}")
            print(f"Listening on: {listen_addr}\n")

            if bootstrap_addr:
                peer_info = info_from_p2p_addr(bootstrap_addr)
                await host.connect(peer_info)
                print(f"Connected to bootstrap peer: {peer_info.peer_id.to_base58()}")
                print("Warming up routing table (5 s)…")
                await trio.sleep(5)

            # ── Run diagnostics ──────────────────────────────────────────────
            diag = dht.get_diagnostics()
            report = diag.analyse()

            print("\n" + "=" * 60)
            print(report.summary())
            print("=" * 60)

            # ── Bucket-level breakdown ───────────────────────────────────────
            print("\nBucket breakdown:")
            print(f"  {'#':>3}  {'Peers':>6}  {'Fill':>6}  Health")
            print(f"  {'-'*3}  {'-'*6}  {'-'*6}  {'-'*8}")
            for stat in report.bucket_stats:
                print(
                    f"  {stat.index:>3}  {stat.peer_count:>6}  "
                    f"{stat.fill_rate * 100:>5.1f}%  {stat.health}"
                )

            # ── Coverage gaps ────────────────────────────────────────────────
            if report.coverage_gaps:
                print(f"\nCoverage gaps ({len(report.coverage_gaps)} buckets below threshold):")
                for gap in report.coverage_gaps[:5]:
                    print(
                        f"  bucket #{gap.bucket_index}: "
                        f"{gap.min_range_hex[:12]}…  ({gap.peer_count} peers)"
                    )
            else:
                print("\nNo coverage gaps detected.")

            # ── Programmatic access ──────────────────────────────────────────
            score = report.health_score
            print(f"\nFinal health score: {score:.1f}/100  ({report.verdict})")
            if score < 40:
                print("  Suggestion: run more random-walk rounds or add bootstrap peers.")

            # Keep bootstrap node alive
            if not bootstrap_addr:
                print("\nBootstrap node running. Press Ctrl-C to stop.")
                await trio.sleep_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="KadDHT routing table diagnostics")
    parser.add_argument("--port", type=int, default=9000, help="TCP port to listen on")
    parser.add_argument(
        "--mode", choices=["server", "client"], default="server",
        help="DHT mode (default: server)"
    )
    parser.add_argument(
        "--bootstrap", default=None,
        metavar="MULTIADDR",
        help="Bootstrap peer multiaddr, e.g. /ip4/127.0.0.1/tcp/8888/p2p/<PeerID>",
    )
    args = parser.parse_args()
    trio.run(run, args.port, args.mode, args.bootstrap)


if __name__ == "__main__":
    main()
