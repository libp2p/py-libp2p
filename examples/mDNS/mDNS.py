import argparse
import logging
import secrets

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.abc import PeerInfo
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.discovery.events.peerDiscovery import peerDiscovery

logger = logging.getLogger("libp2p.discovery.mdns")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(handler)

# Set root logger to DEBUG to capture all logs from dependencies
logging.getLogger().setLevel(logging.DEBUG)


def onPeerDiscovery(peerinfo: PeerInfo):
    logger.info(f"Discovered: {peerinfo.peer_id}")


async def run(port: int) -> None:
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    peerDiscovery.register_peer_discovered_handler(onPeerDiscovery)

    print(
        "Run this from the same folder in another console to "
        "start another peer on a different port:\n\n"
        "mdns-demo -p <ANOTHER_PORT>\n"
    )
    print("Waiting for mDNS peer discovery events...\n")

    logger.info("Starting peer Discovery")
    host = new_host(key_pair=key_pair, enable_mDNS=True)
    async with host.run(listen_addrs=[listen_addr]):
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
