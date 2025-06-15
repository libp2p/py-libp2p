import argparse

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
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

PROTOCOL_ID = TProtocol("/echo/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def _echo_stream_handler(stream: INetStream) -> None:
    # Wait until EOF
    msg = await stream.read(MAX_READ_LEN)
    await stream.write(msg)
    await stream.close()


async def run(port: int, destination: str, seed: int | None = None) -> None:
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    if seed:
        import random

        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        import secrets

        secret = secrets.token_bytes(32)

    host = new_host(key_pair=create_new_key_pair(secret))
    async with host.run(listen_addrs=[listen_addr]):
        print(f"I am {host.get_id().to_string()}")

        if not destination:  # its the server
            host.set_stream_handler(PROTOCOL_ID, _echo_stream_handler)

            print(
                "Run this from the same folder in another console:\n\n"
                f"echo-demo "
                f"-d {host.get_addrs()[0]}\n"
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
        "/ip4/127.0.0.1/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
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
