import argparse
import logging
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

from .assistant import (
    build_assistant,
)

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PROTOCOL_ID = TProtocol("/chat/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def read_data(stream: INetStream, assistant=None) -> None:
    while True:
        read_bytes = await stream.read(MAX_READ_LEN)
        if read_bytes is not None:
            read_string = read_bytes.decode()
            if read_string != "\n":
                # Green console colour: 	\x1b[32m
                # Reset console colour: 	\x1b[0m
                print("\x1b[32m %s\x1b[0m " % read_string, end="")
                if assistant:
                    await assistant.handle_incoming(read_string, stream)


async def write_data(stream: INetStream, assistant=None) -> None:
    async_f = trio.wrap_file(sys.stdin)
    while True:
        line = await async_f.readline()
        await stream.write(line.encode())
        if assistant:
            await assistant.handle_outgoing(line)


async def run(args: argparse.Namespace) -> None:
    from libp2p.utils.address_validation import (
        find_free_port,
        get_available_interfaces,
        get_optimal_binding_address,
    )

    port = args.port
    destination = args.destination
    if port <= 0:
        port = find_free_port()

    listen_addrs = get_available_interfaces(port)
    host = new_host()
    assistant = build_assistant(args)
    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        if not destination:  # its the server

            async def stream_handler(stream: INetStream) -> None:
                nursery.start_soon(read_data, stream, assistant)
                nursery.start_soon(write_data, stream, assistant)

            host.set_stream_handler(PROTOCOL_ID, stream_handler)

            # Get all available addresses with peer ID
            all_addrs = host.get_addrs()

            print("Listener ready, listening on:\n")
            for addr in all_addrs:
                print(f"{addr}")

            # Use optimal address for the client command
            optimal_addr = get_optimal_binding_address(port)
            optimal_addr_with_peer = f"{optimal_addr}/p2p/{host.get_id().to_string()}"
            print(
                f"\nRun this from the same folder in another console:\n\n"
                f"chat-demo -d {optimal_addr_with_peer}\n"
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

            nursery.start_soon(read_data, stream, assistant)
            nursery.start_soon(write_data, stream, assistant)
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
        "--ai-assistant",
        action="store_true",
        help="enable an AI assistant that summarizes or auto-replies",
    )
    parser.add_argument(
        "--ai-mode",
        choices=("summary", "reply"),
        default="summary",
        help="assistant behaviour; default is periodic summaries",
    )
    parser.add_argument(
        "--ai-frequency",
        type=int,
        default=5,
        help="number of messages before the assistant speaks (default: 5)",
    )
    parser.add_argument(
        "--ai-model",
        type=str,
        default=None,
        help="optional Hugging Face model id to override the default",
    )
    args = parser.parse_args()

    try:
        trio.run(run, args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
