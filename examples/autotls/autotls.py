import argparse

import multiaddr
import trio

from libp2p import (
    generate_new_ed25519_identity,
    load_keypair,
    new_host,
    save_keypair,
)
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.identity.identify.identify import (
    ID as IDENTIFY_PROTOCOL_ID,
    identify_handler_for,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.security.tls.transport import (
    PROTOCOL_ID as TLS_PROTOCOL_ID,
    TLSTransport,
)

# Configure minimal logging
# logging.basicConfig(level=logging.WARNING)
# logging.getLogger("multiaddr").setLevel(logging.WARNING)
# logging.getLogger("libp2p").setLevel(logging.WARNING)

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60
PSK = "dffb7e3135399a8b1612b2aaca1c36a3a8ac2cd0cca51ceeb2ced87d308cac6d"
DIRECTORY = {}
ACME_DIRECTORY_URL = "https://acme-staging-v02.api.letsencrypt.org/directory"
PEER_ID_AUTH_SCHEME = "libp2p-PeerID="


async def run(port: int, destination: str, psk: int, transport: str) -> None:
    from libp2p.utils.address_validation import (
        find_free_port,
        get_available_interfaces,
    )

    if port <= 0:
        port = find_free_port()

    if transport == "tcp":
        listen_addrs = get_available_interfaces(port)
    if transport == "ws":
        listen_addrs = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{port}/ws")]

    key_pair = load_keypair()
    if key_pair:
        print("Loaded existing key-pair")
    else:
        print("Generated new key-pair...")
        key_pair = generate_new_ed25519_identity()
        save_keypair(key_pair)

    noise_key_pair = create_new_x25519_key_pair()
    noise_transport = NoiseTransport(key_pair, noise_privkey=noise_key_pair.private_key)
    tls_transport = TLSTransport(key_pair)

    security_options = {
        TLS_PROTOCOL_ID: tls_transport,
        NOISE_PROTOCOL_ID: noise_transport,
    }

    if psk == 1:
        host = new_host(
            key_pair=key_pair,
            listen_addrs=listen_addrs,
            psk=PSK,
            sec_opt=security_options,
            enable_autotls=True,
        )
    else:
        host = new_host(
            key_pair=key_pair, listen_addrs=listen_addrs, sec_opt=security_options
        )

    base_identify_handler = identify_handler_for(host, use_varint_format=False)
    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        if not destination:
            host.set_stream_handler(IDENTIFY_PROTOCOL_ID, base_identify_handler)
            await host.initiate_autotls_procedure()

            # Get all available addresses with peer ID
            all_addrs = host.get_addrs()

            print("Listener ready, listening on:\n")
            for addr in all_addrs:
                print(f"{addr}")

            all_addrs = host.get_addrs()
            if all_addrs:
                print(
                    f"\nRun this from the same folder in another console:\n\n"
                    f"autotls-demo -d {all_addrs[0]} -psk {psk} -t {transport}\n"
                )
            else:
                print("\nWarning: No listening addresses available")
            print("Waiting for incoming connection...")

        else:
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            await host.connect(info)
            stream = await host.new_stream(info.peer_id, [PING_PROTOCOL_ID])
            return

        await trio.sleep_forever()


def main() -> None:
    description = """
    This program demonstrates a simple p2p ping application using libp2p.
    To use it, first run 'python ping.py -p <PORT>', where <PORT> is the port number.
    Then, run another instance with 'python ping.py -p <ANOTHER_PORT> -d <DESTINATION>',
    where <DESTINATION> is the multiaddress of the previous listener host.
    """

    example_maddr = (
        "/ip4/[HOST_IP]/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port number")

    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
    )

    parser.add_argument(
        "-psk", "--psk", default=0, type=int, help="Enable PSK in the transport layer"
    )

    parser.add_argument(
        "-t",
        "--transport",
        default="tcp",
        type=str,
        help="Choose the transport layer for ping TCP/WS",
    )

    args = parser.parse_args()

    try:
        trio.run(run, *(args.port, args.destination, args.psk, args.transport))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
