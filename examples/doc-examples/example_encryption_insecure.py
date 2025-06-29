import secrets

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)


async def main():
    # Create a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create an insecure transport (not recommended for production)
    insecure_transport = InsecureTransport(
        # local_key_pair: The key pair used for libp2p identity
        local_key_pair=key_pair,
        # secure_bytes_provider: Optional function to generate secure random bytes
        # (defaults to secrets.token_bytes)
        secure_bytes_provider=None,  # Use default implementation
        # peerstore: Optional peerstore to store peer IDs and public keys
        # (defaults to None)
        peerstore=None,
    )

    # Create a security options dictionary mapping protocol ID to transport
    security_options = {PLAINTEXT_PROTOCOL_ID: insecure_transport}

    # Create a host with the key pair and insecure transport
    host = new_host(key_pair=key_pair, sec_opt=security_options)

    # Configure the listening address
    port = 8000
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    # Start the host
    async with host.run(listen_addrs=[listen_addr]):
        print(
            "libp2p has started with insecure transport "
            "(not recommended for production)"
        )
        print("libp2p is listening on:", host.get_addrs())
        # Keep the host running
        await trio.sleep_forever()


# Run the async function
trio.run(main)
