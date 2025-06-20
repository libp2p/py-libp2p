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

logger = logging.getLogger("libp2p.example.discovery.mdns")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(handler)


def onPeerDiscovery(peerinfo: PeerInfo):
    logger.info(f"Discovered: {peerinfo.peer_id}")


async def main():
    # Generate a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Listen on a random TCP port
    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")
    peerDiscovery.register_peer_discovered_handler(onPeerDiscovery)
    # Enable mDNS discovery
    logger.info("Starting peer Discovery")
    host = new_host(key_pair=key_pair, enable_mDNS=True)
    await trio.sleep(5)
    async with host.run(listen_addrs=[listen_addr]):
        try:
            while True:
                await trio.sleep(100)
        except KeyboardInterrupt:
            logger.info("Exiting...")


if __name__ == "__main__":
    trio.run(main)
