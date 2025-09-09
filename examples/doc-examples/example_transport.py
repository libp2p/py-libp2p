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
    host = new_host(key_pair=key_pair)

    # Configure the listening address using the new paradigm
    port = 8000
    listen_addrs = get_available_interfaces(port)
    optimal_addr = get_optimal_binding_address(port)

    # Start the host
    async with host.run(listen_addrs=listen_addrs):
        print("libp2p has started with TCP transport")
        print("libp2p is listening on:", host.get_addrs())
        print(f"Optimal address: {optimal_addr}")
        # Keep the host running
        await trio.sleep_forever()


# Run the async function
trio.run(main)
