#!/usr/bin/env python3
"""
QUIC Echo Example - Fixed version with proper client/server separation

This program demonstrates a simple echo protocol using QUIC transport where a peer
listens for connections and copies back any input received on a stream.

Fixed to properly separate client and server modes - clients don't start listeners.
"""

import argparse
import logging

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PROTOCOL_ID = TProtocol("/echo/1.0.0")


async def _echo_stream_handler(stream: INetStream) -> None:
    try:
        msg = await stream.read()
        await stream.write(msg)
        await stream.close()
    except Exception as e:
        print(f"Echo handler error: {e}")
        try:
            await stream.close()
        except:  # noqa: E722
            pass


async def run_server(port: int, seed: int | None = None) -> None:
    """Run echo server with QUIC transport."""
    from libp2p.utils.address_validation import (
        find_free_port,
        get_available_interfaces,
        get_optimal_binding_address,
    )

    if port <= 0:
        port = find_free_port()

    # For QUIC, we need UDP addresses - use the new address paradigm
    tcp_addrs = get_available_interfaces(port)
    # Convert TCP addresses to QUIC addresses
    quic_addrs = []
    for addr in tcp_addrs:
        addr_str = str(addr).replace("/tcp/", "/udp/") + "/quic"
        quic_addrs.append(Multiaddr(addr_str))

    if seed:
        import random

        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        import secrets

        secret = secrets.token_bytes(32)

    # Create host with QUIC transport
    host = new_host(
        enable_quic=True,
        key_pair=create_new_key_pair(secret),
    )

    # Server mode: start listener
    async with host.run(listen_addrs=quic_addrs):
        try:
            print(f"I am {host.get_id().to_string()}")
            host.set_stream_handler(PROTOCOL_ID, _echo_stream_handler)

            # Get all available addresses with peer ID
            all_addrs = host.get_addrs()

            print("Listener ready, listening on:")
            for addr in all_addrs:
                print(f"{addr}")

            # Use optimal address for the client command
            optimal_tcp = get_optimal_binding_address(port)
            optimal_quic_str = str(optimal_tcp).replace("/tcp/", "/udp/") + "/quic"
            peer_id = host.get_id().to_string()
            optimal_quic_with_peer = f"{optimal_quic_str}/p2p/{peer_id}"
            print(
                f"\nRun this from the same folder in another console:\n\n"
                f"python3 ./examples/echo/echo_quic.py -d {optimal_quic_with_peer}\n"
            )
            print("Waiting for incoming QUIC connections...")
            await trio.sleep_forever()
        except KeyboardInterrupt:
            print("Closing server gracefully...")
            await host.close()
            return


async def run_client(destination: str, seed: int | None = None) -> None:
    """Run echo client with QUIC transport."""
    if seed:
        import random

        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        import secrets

        secret = secrets.token_bytes(32)

    # Create host with QUIC transport
    host = new_host(
        enable_quic=True,
        key_pair=create_new_key_pair(secret),
    )

    # Client mode: NO listener, just connect
    async with host.run(listen_addrs=[]):  # Empty listen_addrs for client
        print(f"I am {host.get_id().to_string()}")

        maddr = Multiaddr(destination)
        info = info_from_p2p_addr(maddr)

        # Connect to server
        print("STARTING CLIENT CONNECTION PROCESS")
        await host.connect(info)
        print("CLIENT CONNECTED TO SERVER")

        # Start a stream with the destination
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

        msg = b"hi, there!\n"

        await stream.write(msg)
        response = await stream.read()

        print(f"Sent: {msg.decode('utf-8')}")
        print(f"Got: {response.decode('utf-8')}")
        await stream.close()
        await host.disconnect(info.peer_id)


async def run(port: int, destination: str, seed: int | None = None) -> None:
    """
    Run echo server or client with QUIC transport.

    Fixed version that properly separates client and server modes.
    """
    if not destination:  # Server mode
        await run_server(port, seed)
    else:  # Client mode
        await run_client(destination, seed)


def main() -> None:
    """Main function - help text updated for QUIC."""
    description = """
    This program demonstrates a simple echo protocol using QUIC
    transport where a peer listens for connections and copies back
    any input received on a stream.

    QUIC provides built-in TLS security and stream multiplexing over UDP.

    To use it, first run 'echo-quic-demo -p <PORT>', where <PORT> is
    the UDP port number. Then, run another host with ,
    'echo-quic-demo -d <DESTINATION>'
    where <DESTINATION> is the QUIC multiaddress of the previous listener host.
    """

    example_maddr = "/ip4/[HOST_IP]/udp/8000/quic/p2p/QmQn4SwGkDZKkUEpBRBv"

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="UDP port number")
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
