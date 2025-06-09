import argparse
import sys

import multiaddr
import trio

from libp2p import (
    new_host,
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

PROTOCOL_ID = TProtocol("/chat/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def read_data(stream: INetStream) -> None:
    while True:
        read_bytes = await stream.read(MAX_READ_LEN)
        if read_bytes is not None:
            read_string = read_bytes.decode()
            if read_string != "\n":
                # Green console colour: 	\x1b[32m
                # Reset console colour: 	\x1b[0m
                print("\x1b[32m %s\x1b[0m " % read_string, end="")


async def write_data(stream: INetStream) -> None:
    async_f = trio.wrap_file(sys.stdin)
    while True:
        line = await async_f.readline()
        await stream.write(line.encode())


async def run(port: int, destination: str) -> None:
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    host = new_host()
    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
        if not destination:  # its the server

            async def stream_handler(stream: INetStream) -> None:
                nursery.start_soon(read_data, stream)
                nursery.start_soon(write_data, stream)

            host.set_stream_handler(PROTOCOL_ID, stream_handler)

            print(
                "Run this from the same folder in another console:\n\n"
                f"chat-demo "
                f"-d {host.get_addrs()[0]}\n"
            )
            print("Waiting for incoming connection...")

        else:  # its the client
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            # Associate the peer with local ip address
            await host.connect(info)
            # Start a stream with the destination.
            # Multiaddress of the destination peer is fetched from the peerstore
            # using 'peerId'.
            stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

            nursery.start_soon(read_data, stream)
            nursery.start_soon(write_data, stream)
            print(f"Connected to peer {info.addrs[0]}")

        await trio.sleep_forever()


def main() -> None:
    description = """
    This program demonstrates a simple p2p chat application using libp2p.
    To use it, first run 'python ./chat -p <PORT>', where <PORT> is the port number.
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
    args = parser.parse_args()

    try:
        trio.run(run, *(args.port, args.destination))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
