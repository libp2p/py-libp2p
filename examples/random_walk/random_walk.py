"""
Random Walk Example for py-libp2p Kademlia DHT

This example demonstrates the Random Walk module's peer discovery capabilities
using real libp2p hosts and Kademlia DHT. It shows how the Random Walk module
automatically discovers new peers and maintains routing table health.

Usage:
    # Start server nodes (they will discover peers via random walk)
    python3 random_walk.py --mode server
"""

import argparse
import logging
import random
import secrets
import sys

import trio

from libp2p import new_host
from libp2p.abc import IHost
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.tools.async_service import background_trio_service


# Simple logging configuration
def setup_logging(verbose: bool = False):
    """Setup unified logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    # Configure key module loggers
    for module in ["libp2p.discovery.random_walk", "libp2p.kad_dht"]:
        logging.getLogger(module).setLevel(level)

    # Suppress noisy logs
    logging.getLogger("multiaddr").setLevel(logging.WARNING)


logger = logging.getLogger("random-walk-example")

# Default bootstrap nodes
DEFAULT_BOOTSTRAP_NODES = [
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"
]


def filter_compatible_peer_info(peer_info) -> bool:
    """Filter peer info to check if it has compatible addresses (TCP + IPv4)."""
    if not hasattr(peer_info, "addrs") or not peer_info.addrs:
        return False

    for addr in peer_info.addrs:
        addr_str = str(addr)
        if "/tcp/" in addr_str and "/ip4/" in addr_str and "/quic" not in addr_str:
            return True
    return False


async def maintain_connections(host: IHost) -> None:
    """Maintain connections to ensure the host remains connected to healthy peers."""
    while True:
        try:
            connected_peers = host.get_connected_peers()
            list_peers = host.get_peerstore().peers_with_addrs()

            if len(connected_peers) < 20:
                logger.debug("Reconnecting to maintain peer connections...")

                # Find compatible peers
                compatible_peers = []
                for peer_id in list_peers:
                    try:
                        peer_info = host.get_peerstore().peer_info(peer_id)
                        if filter_compatible_peer_info(peer_info):
                            compatible_peers.append(peer_id)
                    except Exception:
                        continue

                # Connect to random subset of compatible peers
                if compatible_peers:
                    random_peers = random.sample(
                        compatible_peers, min(50, len(compatible_peers))
                    )
                    for peer_id in random_peers:
                        if peer_id not in connected_peers:
                            try:
                                with trio.move_on_after(5):
                                    peer_info = host.get_peerstore().peer_info(peer_id)
                                    await host.connect(peer_info)
                                    logger.debug(f"Connected to peer: {peer_id}")
                            except Exception as e:
                                logger.debug(f"Failed to connect to {peer_id}: {e}")

            await trio.sleep(15)
        except Exception as e:
            logger.error(f"Error maintaining connections: {e}")


async def demonstrate_random_walk_discovery(dht: KadDHT, interval: int = 30) -> None:
    """Demonstrate Random Walk peer discovery with periodic statistics."""
    iteration = 0
    while True:
        iteration += 1
        logger.info(f"--- Iteration {iteration} ---")
        logger.info(f"Routing table size: {dht.get_routing_table_size()}")
        logger.info(f"Connected peers: {len(dht.host.get_connected_peers())}")
        logger.info(f"Peerstore size: {len(dht.host.get_peerstore().peer_ids())}")
        await trio.sleep(interval)


async def run_node(port: int, mode: str, demo_interval: int = 30) -> None:
    """Run a node that demonstrates Random Walk peer discovery."""
    try:
        if port <= 0:
            port = random.randint(10000, 60000)

        logger.info(f"Starting {mode} node on port {port}")

        # Determine DHT mode
        dht_mode = DHTMode.SERVER if mode == "server" else DHTMode.CLIENT

        # Create host and DHT
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        host = new_host(key_pair=key_pair, bootstrap=DEFAULT_BOOTSTRAP_NODES)

        from libp2p.utils.address_validation import get_available_interfaces

        listen_addrs = get_available_interfaces(port)

        async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
            # Start maintenance tasks
            nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
            nursery.start_soon(maintain_connections, host)

            peer_id = host.get_id().pretty()
            logger.info(f"Node peer ID: {peer_id}")

            # Get all available addresses with peer ID
            all_addrs = host.get_addrs()
            logger.info("Listener ready, listening on:")
            for addr in all_addrs:
                logger.info(f"{addr}")

            # Create and start DHT with Random Walk enabled
            dht = KadDHT(host, dht_mode, enable_random_walk=True)
            logger.info(f"Initial routing table size: {dht.get_routing_table_size()}")

            async with background_trio_service(dht):
                logger.info(f"DHT service started in {dht_mode.value} mode")
                logger.info(f"Random Walk enabled: {dht.is_random_walk_enabled()}")

                async with trio.open_nursery() as task_nursery:
                    # Start demonstration and status reporting
                    task_nursery.start_soon(
                        demonstrate_random_walk_discovery, dht, demo_interval
                    )

                    # Periodic status updates
                    async def status_reporter():
                        while True:
                            await trio.sleep(30)
                            logger.debug(
                                f"Connected: {len(dht.host.get_connected_peers())}, "
                                f"Routing table: {dht.get_routing_table_size()}, "
                                f"Peerstore: {len(dht.host.get_peerstore().peer_ids())}"
                            )

                    task_nursery.start_soon(status_reporter)
                    await trio.sleep_forever()

    except Exception as e:
        logger.error(f"Node error: {e}", exc_info=True)
        sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Random Walk Example for py-libp2p Kademlia DHT",
    )
    parser.add_argument(
        "--mode",
        choices=["server", "client"],
        default="server",
        help="Node mode: server (DHT server), or client (DHT client)",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="Port to listen on (0 for random)"
    )
    parser.add_argument(
        "--demo-interval",
        type=int,
        default=30,
        help="Interval between random walk demonstrations in seconds",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def main():
    """Main entry point for the random walk example."""
    try:
        args = parse_args()
        setup_logging(args.verbose)

        logger.info("=== Random Walk Example for py-libp2p ===")
        logger.info(
            f"Mode: {args.mode}, Port: {args.port} Demo interval: {args.demo_interval}s"
        )

        trio.run(run_node, args.port, args.mode, args.demo_interval)

    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.critical(f"Example failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
