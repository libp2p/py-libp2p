import argparse
import logging
import secrets

import trio

from libp2p import (
    new_host,
)
from libp2p.abc import PeerInfo
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.discovery.events.peerDiscovery import peerDiscovery

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

logger = logging.getLogger("libp2p.discovery.mdns")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(handler)


def onPeerDiscovery(peerinfo: PeerInfo):
    logger.info(f"Discovered: {peerinfo.peer_id}")


async def run(port: int) -> None:
    from libp2p.utils.address_validation import find_free_port, get_available_interfaces

    if port <= 0:
        port = find_free_port()

    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)
    listen_addrs = get_available_interfaces(port)

    peerDiscovery.register_peer_discovered_handler(onPeerDiscovery)

    logger.info("Starting peer Discovery")
    host = new_host(key_pair=key_pair, enable_mDNS=True)
    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        # Get all available addresses with peer ID
        all_addrs = host.get_addrs()

        print("Listener ready, listening on:")
        for addr in all_addrs:
            print(f"{addr}")

        print(
            "\nRun this from the same folder in another console to "
            "start another peer on a different port:\n\n"
            "mdns-demo -p <ANOTHER_PORT>\n"
        )
        print("Waiting for mDNS peer discovery events...\n")

        await trio.sleep_forever()


def main() -> None:
    description = """
    This program demonstrates mDNS peer discovery using libp2p.
    To use it, run 'mdns-demo -p <PORT>', where <PORT> is the port number.
    Start multiple peers on different ports to see discovery in action.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port number")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    try:
        trio.run(run, args.port)
    except KeyboardInterrupt:
        logger.info("Exiting...")


if __name__ == "__main__":
    main()
