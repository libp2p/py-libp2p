import secrets

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.discovery.events.peerDiscovery import (
    peerDiscovery
)
from libp2p.abc import (
    PeerInfo
)

def customFunctoion(peerinfo: PeerInfo):
    print("Printing peer info from demo file",repr(peerinfo))


async def main():
    # Generate a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Listen on a random TCP port
    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")
    peerDiscovery.register_peer_discovered_handler(customFunctoion)
    # Enable mDNS discovery
    host = new_host(key_pair=key_pair, enable_mDNS=True)

    async with host.run(listen_addrs=[listen_addr]):
        # Print discovered peers via mDNS
        try:
            while True:
                await trio.sleep(100)
        except KeyboardInterrupt:
            print("Exiting...")


if __name__ == "__main__":
    trio.run(main)
