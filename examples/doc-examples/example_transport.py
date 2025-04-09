import secrets

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)


async def main():
    # Create a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create a host with the key pair
    host = new_host(key_pair=key_pair)

    # Configure the listening address
    port = 8000
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    # Start the host
    async with host.run(listen_addrs=[listen_addr]):
        print("libp2p has started with TCP transport")
        print("libp2p is listening on:", host.get_addrs())
        # Keep the host running
        await trio.sleep_forever()


# Run the async function
trio.run(main)
