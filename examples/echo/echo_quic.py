#!/usr/bin/env python3
"""
QUIC Echo Example - Direct replacement for examples/echo/echo.py

This program demonstrates a simple echo protocol using QUIC transport where a peer
listens for connections and copies back any input received on a stream.

Modified from the original TCP version to use QUIC transport, providing:
- Built-in TLS security
- Native stream multiplexing
- Better performance over UDP
- Modern QUIC protocol features
"""

import argparse

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.transport.quic.config import QUICTransportConfig

PROTOCOL_ID = TProtocol("/echo/1.0.0")


async def _echo_stream_handler(stream: INetStream) -> None:
    """
    Echo stream handler - unchanged from TCP version.

    Demonstrates transport abstraction: same handler works for both TCP and QUIC.
    """
    # Wait until EOF
    msg = await stream.read()
    await stream.write(msg)
    await stream.close()


async def run(port: int, destination: str, seed: int | None = None) -> None:
    """
    Run echo server or client with QUIC transport.

    Key changes from TCP version:
    1. UDP multiaddr instead of TCP
    2. QUIC transport configuration
    3. Everything else remains the same!
    """
    # CHANGED: UDP + QUIC instead of TCP
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/udp/{port}/quic")

    if seed:
        import random

        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        import secrets

        secret = secrets.token_bytes(32)

    # NEW: QUIC transport configuration
    quic_config = QUICTransportConfig(
        idle_timeout=30.0,
        max_concurrent_streams=1000,
        connection_timeout=10.0,
    )

    # CHANGED: Add QUIC transport options
    host = new_host(
        key_pair=create_new_key_pair(secret),
        transport_opt={"quic_config": quic_config},
    )

    async with host.run(listen_addrs=[listen_addr]):
        print(f"I am {host.get_id().to_string()}")

        if not destination:  # Server mode
            host.set_stream_handler(PROTOCOL_ID, _echo_stream_handler)

            print(
                "Run this from the same folder in another console:\n\n"
                f"python3 ./examples/echo/echo_quic.py "
                f"-d {host.get_addrs()[0]}\n"
            )
            print("Waiting for incoming QUIC connections...")
            await trio.sleep_forever()

        else:  # Client mode
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
            # Notify the other side about EOF
            await stream.close()
            response = await stream.read()

            print(f"Sent: {msg.decode('utf-8')}")
            print(f"Got: {response.decode('utf-8')}")


def main() -> None:
    """Main function - help text updated for QUIC."""
    description = """
    This program demonstrates a simple echo protocol using QUIC
    transport where a peer listens for connections and copies back
    any input received on a stream.

    QUIC provides built-in TLS security and stream multiplexing over UDP.

    To use it, first run 'python ./echo.py -p <PORT>', where <PORT> is
    the UDP port number.Then, run another host with ,
    'python ./echo.py -p <ANOTHER_PORT> -d <DESTINATION>'
    where <DESTINATION> is the QUIC multiaddress of the previous listener host.
    """

    example_maddr = "/ip4/127.0.0.1/udp/8000/quic/p2p/QmQn4SwGkDZKkUEpBRBv"

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=8000, type=int, help="UDP port number")
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
        help="provide a seed to the random number generator",
    )
    args = parser.parse_args()
    try:
        trio.run(run, args.port, args.destination, args.seed)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
