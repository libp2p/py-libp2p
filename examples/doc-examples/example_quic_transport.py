import secrets

import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.utils.address_validation import (
    get_available_interfaces,
    get_optimal_binding_address,
)


async def main():
    # Create a key pair for the host
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create a host with the key pair
    host = new_host(key_pair=key_pair, enable_quic=True)

    # Configure the listening address using the new paradigm
    port = 8000
    listen_addrs = get_available_interfaces(port, protocol="udp")
    # Convert TCP addresses to QUIC-v1 addresses
    quic_addrs = []
    for addr in listen_addrs:
        addr_str = str(addr).replace("/tcp/", "/udp/") + "/quic-v1"
        from multiaddr import Multiaddr

        quic_addrs.append(Multiaddr(addr_str))

    optimal_addr = get_optimal_binding_address(port, protocol="udp")
    optimal_quic_str = str(optimal_addr).replace("/tcp/", "/udp/") + "/quic-v1"

    # Start the host
    async with host.run(listen_addrs=quic_addrs):
        print("libp2p has started with QUIC transport")
        print("libp2p is listening on:", host.get_addrs())
        print(f"Optimal address: {optimal_quic_str}")
        # Keep the host running
        await trio.sleep_forever()


# Run the async function
trio.run(main)
