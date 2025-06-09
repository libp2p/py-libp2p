import secrets

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)


async def main():
    # Create a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create a Noise security transport
    noise_transport = NoiseTransport(
        # local_key_pair: The key pair used for libp2p identity and authentication
        libp2p_keypair=key_pair,
        # noise_privkey: The private key used for Noise protocol encryption
        noise_privkey=key_pair.private_key,
        # early_data: Optional data to send during the handshake
        # (None means no early data)
        early_data=None,
        # with_noise_pipes: Whether to use Noise pipes for additional security features
        with_noise_pipes=False,
    )

    # Create a security options dictionary mapping protocol ID to transport
    security_options = {NOISE_PROTOCOL_ID: noise_transport}

    # Create a host with the key pair, Noise security, and mplex multiplexer
    host = new_host(key_pair=key_pair, sec_opt=security_options)

    # Configure the listening address
    port = 8000
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    # Start the host
    async with host.run(listen_addrs=[listen_addr]):
        print("libp2p has started")
        print("libp2p is listening on:", host.get_addrs())
        # Keep the host running
        await trio.sleep_forever()


# Run the async function
trio.run(main)
