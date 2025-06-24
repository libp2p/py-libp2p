import argparse

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

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60


async def handle_ping(stream: INetStream) -> None:
    while True:
        try:
            payload = await stream.read(PING_LENGTH)
            peer_id = stream.muxed_conn.peer_id
            if payload is not None:
                print(f"received ping from {peer_id}")

                await stream.write(payload)
                print(f"responded with pong to {peer_id}")

        except Exception:
            await stream.reset()
            break


async def send_ping(stream: INetStream) -> None:
    try:
        payload = b"\x01" * PING_LENGTH
        print(f"sending ping to {stream.muxed_conn.peer_id}")

        await stream.write(payload)

        with trio.fail_after(RESP_TIMEOUT):
            response = await stream.read(PING_LENGTH)

        if response == payload:
            print(f"received pong from {stream.muxed_conn.peer_id}")

    except Exception as e:
        print(f"error occurred : {e}")


async def run(port: int, destination: str) -> None:
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    host = new_host(listen_addrs=[listen_addr])

    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
        if not destination:
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

            print(
                "Run this from the same folder in another console:\n\n"
                f"ping-demo "
                f"-d {host.get_addrs()[0]}\n"
            )
            print("Waiting for incoming connection...")

        else:
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            await host.connect(info)
            stream = await host.new_stream(info.peer_id, [PING_PROTOCOL_ID])

            nursery.start_soon(send_ping, stream)

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
