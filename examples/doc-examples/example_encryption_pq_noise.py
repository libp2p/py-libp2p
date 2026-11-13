import secrets

import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.security.noise.pq.transport_pq import (
    PROTOCOL_ID as PQ_NOISE_PROTOCOL_ID,
    TransportPQ,
)
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.utils.address_validation import (
    get_available_interfaces,
    get_optimal_binding_address,
)


async def main():
    # Create a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create the experimental post-quantum Noise transport (X25519 + ML-KEM-768).
    # It needs `pip install 'libp2p[pq]'` for the ML-KEM-768 backend.
    pq_noise_transport = TransportPQ(
        libp2p_keypair=key_pair,
        noise_privkey=create_new_x25519_key_pair().private_key,
    )

    # Create the classical Noise transport as a fallback
    noise_transport = NoiseTransport(
        libp2p_keypair=key_pair,
        noise_privkey=create_new_x25519_key_pair().private_key,
    )

    # Security protocols are proposed in insertion order, so this prefers
    # post-quantum Noise and falls back to classical Noise. Leave out the
    # classical entry to refuse peers that cannot speak post-quantum Noise.
    security_options = {
        PQ_NOISE_PROTOCOL_ID: pq_noise_transport,
        NOISE_PROTOCOL_ID: noise_transport,
    }

    # Create a host with the key pair and both security transports
    host = new_host(key_pair=key_pair, sec_opt=security_options)

    # Configure the listening address using the new paradigm
    port = 8000
    listen_addrs = get_available_interfaces(port)
    optimal_addr = get_optimal_binding_address(port)

    # Start the host
    async with host.run(listen_addrs=listen_addrs):
        print("libp2p has started with post-quantum Noise encryption")
        print("libp2p is listening on:", host.get_addrs())
        print(f"Optimal address: {optimal_addr}")
        # Keep the host running
        await trio.sleep_forever()


# Run the async function
trio.run(main)
