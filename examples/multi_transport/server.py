#!/usr/bin/env python3
"""
Multi-Transport Echo Server — py-libp2p

Demonstrates listening on TCP, WebSocket, and QUIC simultaneously,
mirroring go-libp2p's multi-transport architecture.

Usage:
    # Start server (auto-detects free ports on all transports):
    python server.py

    # Start server on specific port:
    python server.py --port 4001

    # Start client (copy one of the multiaddrs printed by the server):
    python client.py -d /ip4/127.0.0.1/tcp/4001/p2p/<PEER_ID>
    python client.py -d /ip4/127.0.0.1/tcp/4001/ws/p2p/<PEER_ID>
    python client.py -d /ip4/127.0.0.1/udp/4001/quic/p2p/<PEER_ID>
"""

import argparse
import logging
from pathlib import Path
import sys

# Ensure local libp2p is used
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.utils.address_validation import find_free_port

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

ECHO_PROTOCOL = TProtocol("/echo/1.0.0")


async def _echo_handler(stream: INetStream) -> None:
    """Echo handler: read up to 1024 bytes and write it back."""
    try:
        peer_id = stream.muxed_conn.peer_id
        # Read a chunk rather than wait for EOF, preventing deadlocks
        # if the client keeps it open
        data = await stream.read(1024)
        print(f"  [{peer_id!s:.20}...] echoing {len(data)} bytes")
        await stream.write(data)
        await stream.close()
    except Exception as exc:
        print(f"  Handler error: {exc}")
        try:
            await stream.reset()
        except Exception:
            pass


async def run_server(port: int = 0) -> None:
    """
    Listen simultaneously on TCP, WebSocket, and QUIC using the EXACT SAME PORT.
    This demonstrates py-libp2p's connection multiplexing (cmux) capabilities.
    """
    if port == 0:
        port = find_free_port()

    # Build listen addresses for all three transports on the SAME port
    listen_addrs = [
        multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}"),  # plain TCP
        multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/ws"),  # WebSocket
        multiaddr.Multiaddr(f"/ip4/0.0.0.0/udp/{port}/quic"),  # QUIC
    ]

    host = new_host(key_pair=create_new_key_pair(), listen_addrs=listen_addrs)
    host.set_stream_handler(ECHO_PROTOCOL, _echo_handler)

    print("=== Multi-Transport CMUX Echo Server ===\n")
    print(f"Using shared port: {port}\n")
    print("Listening on:")

    async with host.run(listen_addrs=listen_addrs):
        # Wait until the host has bound and resolved all ports
        for _ in range(50):
            if host.get_addrs():
                break
            await trio.sleep(0.05)

        peer_id = host.get_id().to_string()
        for addr in host.get_addrs():
            print(f"  {addr}")

        print(
            "\nConnect using any of the following (replace 0.0.0.0 with your IP):\n\n"
            f"  TCP:       python client.py -d "
            f"/ip4/127.0.0.1/tcp/{port}/p2p/{peer_id}\n"
            f"  WebSocket: python client.py -d "
            f"/ip4/127.0.0.1/tcp/{port}/ws/p2p/{peer_id}\n"
            f"  QUIC:      python client.py -d "
            f"/ip4/127.0.0.1/udp/{port}/quic/p2p/{peer_id}"
        )
        print("\nWaiting for connections… (Ctrl-C to stop)\n")

        await trio.sleep_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CMUX echo server (TCP + WebSocket + QUIC on SAME port)."
    )
    parser.add_argument(
        "--port", type=int, default=0, help="Listen port for all transports (0 = auto)"
    )
    args = parser.parse_args()
    try:
        trio.run(run_server, args.port)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
