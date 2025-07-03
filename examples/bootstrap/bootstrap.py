import argparse
import logging
import secrets

import multiaddr
import trio

from libp2p import new_host
from libp2p.abc import PeerInfo
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.discovery.events.peerDiscovery import peerDiscovery

# Configure logging
logger = logging.getLogger("libp2p.discovery.bootstrap")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(handler)

# Set root logger to DEBUG to capture all logs
logging.getLogger().setLevel(logging.DEBUG)


def on_peer_discovery(peer_info: PeerInfo) -> None:
    """Handler for peer discovery events."""
    logger.info(f"🔍 Discovered peer: {peer_info.peer_id}")
    logger.info(f"   Addresses: {[str(addr) for addr in peer_info.addrs]}")


# Example bootstrap peers (you can replace with real bootstrap nodes)
BOOTSTRAP_PEERS = [
    # IPFS bootstrap nodes (examples - replace with actual working nodes)
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SznbYGzPwp8qDrq",
    "/ip6/2604:a880:1:20::203:d001/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM",
]


async def run(port: int, bootstrap_addrs: list[str]) -> None:
    """Run the bootstrap discovery example."""
    # Generate key pair
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create listen address
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    # Register peer discovery handler
    peerDiscovery.register_peer_discovered_handler(on_peer_discovery)

    logger.info("🚀 Starting Bootstrap Discovery Example")
    logger.info(f"📍 Listening on: {listen_addr}")
    logger.info(f"🌐 Bootstrap peers: {len(bootstrap_addrs)}")

    print("\n" + "=" * 60)
    print("Bootstrap Discovery Example")
    print("=" * 60)
    print("This example demonstrates connecting to bootstrap peers.")
    print("Watch the logs for peer discovery events!")
    print("Press Ctrl+C to exit.")
    print("=" * 60)

    # Create and run host with bootstrap discovery
    host = new_host(key_pair=key_pair, bootstrap=bootstrap_addrs)

    try:
        async with host.run(listen_addrs=[listen_addr]):
            # Keep running and log peer discovery events
            await trio.sleep_forever()
    except KeyboardInterrupt:
        logger.info("👋 Shutting down...")


def main() -> None:
    """Main entry point."""
    description = """
    Bootstrap Discovery Example for py-libp2p

    This example demonstrates how to use bootstrap peers for peer discovery.
    Bootstrap peers are predefined peers that help new nodes join the network.

    Usage:
        python bootstrap.py -p 8000
        python bootstrap.py -p 8001 --custom-bootstrap \\
            "/ip4/127.0.0.1/tcp/8000/p2p/QmYourPeerID"
    """

    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-p", "--port", default=0, type=int, help="Port to listen on (default: random)"
    )
    parser.add_argument(
        "--custom-bootstrap",
        nargs="*",
        help="Custom bootstrap addresses (space-separated)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Use custom bootstrap addresses if provided, otherwise use defaults
    bootstrap_addrs = (
        args.custom_bootstrap if args.custom_bootstrap else BOOTSTRAP_PEERS
    )

    try:
        trio.run(run, args.port, bootstrap_addrs)
    except KeyboardInterrupt:
        logger.info("Exiting...")


if __name__ == "__main__":
    main()
