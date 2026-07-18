import argparse
import logging
import secrets

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

# Configure root logger to only show warnings and above to reduce noise
# This prevents verbose DEBUG messages from multiaddr, DNS, etc.
logging.getLogger().setLevel(logging.WARNING)

# Specifically silence noisy libraries
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("root").setLevel(logging.WARNING)


def on_peer_discovery(peer_info: PeerInfo) -> None:
    """Handler for peer discovery events."""
    logger.info(f"🔍 Discovered peer: {peer_info.peer_id}")
    logger.debug(f"   Addresses: {[str(addr) for addr in peer_info.addrs]}")


# Example bootstrap peers
BOOTSTRAP_PEERS = [
    "/dnsaddr/github.com/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/cloudflare.com/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/google.com/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
    "/ip6/2604:a880:1:20::203:d001/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM",
    "/ip4/128.199.219.111/tcp/4001/p2p/QmSoLV4Bbm51jM9C4gDYZQ9Cy3U6aXMJDAbzgu2fzaDs64",
    "/ip4/104.236.76.40/tcp/4001/p2p/QmSoLV4Bbm51jM9C4gDYZQ9Cy3U6aXMJDAbzgu2fzaDs64",
    "/ip4/178.62.158.247/tcp/4001/p2p/QmSoLer265NRgSp2LA3dPaeykiS1J6DifTC88f5uVQKNAd",
    "/ip6/2604:a880:1:20::203:d001/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM",
    "/ip6/2400:6180:0:d0::151:6001/tcp/4001/p2p/QmSoLSafTMBsPKadTEgaXctDQVcqN88CNLHXMkTNwMKPnu",
    "/ip6/2a03:b0c0:0:1010::23:1001/tcp/4001/p2p/QmSoLueR4xBeUbY9WZ9xGUUxunbKWcrNFTDAadQJmocnWm",
]


async def run(port: int, bootstrap_addrs: list[str]) -> None:
    """Run the bootstrap discovery example."""
    from libp2p.utils.address_validation import (
        find_free_port,
        get_available_interfaces,
        get_optimal_binding_address,
    )

    if port <= 0:
        port = find_free_port()

    # Generate key pair
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create listen addresses for all available interfaces
    listen_addrs = get_available_interfaces(port)

    # Register peer discovery handler
    peerDiscovery.register_peer_discovered_handler(on_peer_discovery)

    logger.info("🚀 Starting Bootstrap Discovery Example")
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
        async with host.run(listen_addrs=listen_addrs):
            # Get all available addresses with peer ID
            all_addrs = host.get_addrs()

            logger.info("Listener ready, listening on:")
            print("Listener ready, listening on:")
            for addr in all_addrs:
                logger.info(f"{addr}")
                print(f"{addr}")

            # Display optimal address for reference
            optimal_addr = get_optimal_binding_address(port)
            optimal_addr_with_peer = f"{optimal_addr}/p2p/{host.get_id().to_string()}"
            logger.info(f"Optimal address: {optimal_addr_with_peer}")
            print(f"Optimal address: {optimal_addr_with_peer}")

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
            "/ip4/[HOST_IP]/tcp/8000/p2p/QmYourPeerID"
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
