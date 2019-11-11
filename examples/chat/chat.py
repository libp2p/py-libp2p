import argparse
import asyncio
import trio_asyncio
import trio
import sys
import urllib.request

import multiaddr

from libp2p import new_node
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.typing import TProtocol

PROTOCOL_ID = TProtocol("/chat/1.0.0")
MAX_READ_LEN = 2 ** 32 - 1


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
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        await stream.write(line.encode())


async def run(port: int, destination: str, localhost: bool) -> None:
    if localhost:
        ip = "127.0.0.1"
    else:
        ip = urllib.request.urlopen("https://v4.ident.me/").read().decode("utf8")
    transport_opt = f"/ip4/{ip}/tcp/{port}"
    host = await new_node(transport_opt=[transport_opt])

    await host.get_network().listen(multiaddr.Multiaddr(transport_opt))

    if not destination:  # its the server

        async def stream_handler(stream: INetStream) -> None:
            asyncio.ensure_future(read_data(stream))
            asyncio.ensure_future(write_data(stream))

        host.set_stream_handler(PROTOCOL_ID, stream_handler)

        localhost_opt = " --localhost" if localhost else ""

        print(
            f"Run 'python ./examples/chat/chat.py"
            + localhost_opt
            + f" -p {int(port) + 1} -d /ip4/{ip}/tcp/{port}/p2p/{host.get_id().pretty()}'"
            + " on another console."
        )
        print("Waiting for incoming connection...")

    else:  # its the client
        maddr = multiaddr.Multiaddr(destination)
        info = info_from_p2p_addr(maddr)
        # Associate the peer with local ip address
        await host.connect(info)

        # Start a stream with the destination.
        # Multiaddress of the destination peer is fetched from the peerstore using 'peerId'.
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

        asyncio.ensure_future(read_data(stream))
        asyncio.ensure_future(write_data(stream))
        print("Connected to peer %s" % info.addrs[0])

async def async_main_wrapper(*args):
    async with trio_asyncio.open_loop() as loop:
        assert loop == asyncio.get_event_loop()
        await run(*args)

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
    args = parser.parse_args()

    if not args.port:
        raise RuntimeError("was not able to determine a local port")

    trio.run(async_main_wrapper, *(args.port, args.destination, args.localhost))

if __name__ == "__main__":
    main()
