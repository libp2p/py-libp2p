import secrets

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.security.secio.transport import (
    ID as SECIO_PROTOCOL_ID,
    Transport as SecioTransport,
)


async def main():
    # Create a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create a SECIO security transport
    secio_transport = SecioTransport(
        # local_key_pair: The key pair used for libp2p identity and authentication
        local_key_pair=key_pair,
    )

    # Create a security options dictionary mapping protocol ID to transport
    security_options = {SECIO_PROTOCOL_ID: secio_transport}

    # Create a host with the key pair and SECIO security
    host = new_host(key_pair=key_pair, sec_opt=security_options)

    # Configure the listening address
    port = 8000
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    # Start the host
    async with host.run(listen_addrs=[listen_addr]):
        print("libp2p has started with SECIO encryption")
        print("libp2p is listening on:", host.get_addrs())
        # Keep the host running
        await trio.sleep_forever()


# Run the async function
trio.run(main)
