import secrets

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.abc import (
    PeerInfo,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.discovery.events.peerDiscovery import (
    peerDiscovery,
)


async def main():
    # Generate a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Listen on a random TCP port
    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")

    # Enable mDNS discovery
    host = new_host(key_pair=key_pair, enable_mDNS=True)

    async with host.run(listen_addrs=[listen_addr]):
        print("host peer id", host.get_id())

        # Print discovered peers via mDNS
        print("Waiting for mDNS peer discovery events (Ctrl+C to exit)...")
        try:
            while True:
                peer_info = PeerInfo(host.get_id(), host.get_addrs())

                await trio.sleep(1)
                await peerDiscovery.emit_peer_discovered(peer_info=peer_info)
        except KeyboardInterrupt:
            print("Exiting...")


if __name__ == "__main__":
    trio.run(main)
