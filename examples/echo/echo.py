import argparse
import asyncio
import urllib.request

import multiaddr

from libp2p import new_node
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.typing import TProtocol

PROTOCOL_ID = TProtocol("/echo/1.0.0")


async def _echo_stream_handler(stream: INetStream) -> None:
    msg = await stream.read()
    await stream.write(msg)
    await stream.close()


async def run(port: int, destination: str, localhost: bool, seed: int = None) -> None:
    if localhost:
        ip = "127.0.0.1"
    else:
        ip = urllib.request.urlopen("https://v4.ident.me/").read().decode("utf8")
    transport_opt = f"/ip4/{ip}/tcp/{port}"

    if seed:
        import random

        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        import secrets

        secret = secrets.token_bytes(32)

    host = await new_node(
        key_pair=create_new_key_pair(secret), transport_opt=[transport_opt]
    )

    print(f"I am {host.get_id().to_string()}")

    await host.get_network().listen(multiaddr.Multiaddr(transport_opt))

    if not destination:  # its the server

        host.set_stream_handler(PROTOCOL_ID, _echo_stream_handler)

        localhost_opt = " --localhost" if localhost else ""

        print(
            f"Run 'python ./examples/echo/echo.py"
            + localhost_opt
            + f" -p {int(port) + 1} -d /ip4/{ip}/tcp/{port}/p2p/{host.get_id().pretty()}'"
            + " on another console."
        )
        print("Waiting for incoming connections...")

    else:  # its the client
        maddr = multiaddr.Multiaddr(destination)
        info = info_from_p2p_addr(maddr)
        # Associate the peer with local ip address
        await host.connect(info)

        # Start a stream with the destination.
        # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

        msg = b"hi, there!\n"

        await stream.write(msg)
        # Notify the other side about EOF
        await stream.close()
        response = await stream.read()

        print(f"Sent: {msg}")
        print(f"Got: {response}")


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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="generate the same node ID on every execution",
    )
    parser.add_argument(
        "-p", "--port", default=8000, type=int, help="source port number"
    )
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
    )
    parser.add_argument(
        "-l",
        "--localhost",
        dest="localhost",
        action="store_true",
        help="flag indicating if localhost should be used or an external IP",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help="provide a seed to the random number generator (e.g. to fix peer IDs across runs)",
    )
    args = parser.parse_args()

    if not args.port:
        raise RuntimeError("was not able to determine a local port")

    loop = asyncio.get_event_loop()
    try:
        asyncio.ensure_future(
            run(args.port, args.destination, args.localhost, args.seed)
        )
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
