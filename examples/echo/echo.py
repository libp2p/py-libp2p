import argparse
import logging
import random
import secrets

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.exceptions import (
    StreamEOF,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
)

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PROTOCOL_ID = TProtocol("/echo/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def _echo_stream_handler(stream: INetStream) -> None:
    try:
        peer_id = stream.muxed_conn.peer_id
        print(f"Received connection from {peer_id}")
        # Wait until EOF
        msg = await stream.read(MAX_READ_LEN)
        print(f"Echoing message: {msg.decode('utf-8')}")
        await stream.write(msg)
    except StreamEOF:
        print("Stream closed by remote peer.")
    except Exception as e:
        print(f"Error in echo handler: {e}")
    finally:
        await stream.close()


async def run(port: int, destination: str, seed: int | None = None) -> None:
    if port <= 0:
        port = find_free_port()
    listen_addr = get_available_interfaces(port)

    if seed:
        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        secret = secrets.token_bytes(32)

    host = new_host(key_pair=create_new_key_pair(secret))
    async with host.run(listen_addrs=listen_addr), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        print(f"I am {host.get_id().to_string()}")

        if not destination:  # its the server
            host.set_stream_handler(PROTOCOL_ID, _echo_stream_handler)

            # Print all listen addresses with peer ID (JS parity)
            print("Listener ready, listening on:\n")
            peer_id = host.get_id().to_string()
            for addr in listen_addr:
                print(f"{addr}/p2p/{peer_id}")

            # Get optimal address for display
            optimal_addr = get_optimal_binding_address(port)
            optimal_addr_with_peer = f"{optimal_addr}/p2p/{peer_id}"

            print(
                "\nRun this from the same folder in another console:\n\n"
                f"echo-demo -d {optimal_addr_with_peer}\n"
            )
            print("Waiting for incoming connections...")
            await trio.sleep_forever()

        else:  # its the client
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            # Associate the peer with local ip address
            await host.connect(info)

            # Start a stream with the destination.
            # Multiaddress of the destination peer is fetched from the peerstore
            # using 'peerId'.
            stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

            msg = b"hi, there!\n"

            await stream.write(msg)
            response = await stream.read()
            await stream.close()

            print(f"Sent: {msg.decode('utf-8')}")
            print(f"Got: {response.decode('utf-8')}")


def main() -> None:
    description = """
    This program demonstrates a simple echo protocol where a peer listens for
    connections and copies back any input received on a stream.

    To use it, first run 'python ./echo -p <PORT>', where <PORT> is the port number.
    Then, run another host with 'python ./chat -p <ANOTHER_PORT> -d <DESTINATION>',
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
        "-s",
        "--seed",
        type=int,
        help="provide a seed to the random number generator (e.g. to fix peer IDs across runs)",  # noqa: E501
    )
    args = parser.parse_args()
    try:
        trio.run(run, args.port, args.destination, args.seed)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
