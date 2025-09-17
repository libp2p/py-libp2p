import secrets

from multiaddr import Multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
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

    # Configure the listening address using the new paradigm
    port = 8000
    listen_addrs = get_available_interfaces(port)
    optimal_addr = get_optimal_binding_address(port)

    # Start the host
    async with host.run(listen_addrs=listen_addrs):
        print("libp2p has started")
        print("libp2p is listening on:", host.get_addrs())
        print(f"Optimal address: {optimal_addr}")

        # Connect to bootstrap peers manually
        bootstrap_list = [
            "/dnsaddr/bootstrap.libp2p.io/p2p/"
            + "QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
            "/dnsaddr/bootstrap.libp2p.io/p2p/"
            + "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
        ]

        for addr in bootstrap_list:
            try:
                peer_info = info_from_p2p_addr(Multiaddr(addr))
                await host.connect(peer_info)
                print(f"Connected to {peer_info.peer_id.to_string()}")
            except Exception as e:
                print(f"Failed to connect to {addr}: {e}")

        # Keep the host running
        await trio.sleep_forever()


# Run the async function
trio.run(main)
