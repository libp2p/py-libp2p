#!/usr/bin/env python3
"""
Multi-Transport Echo Server — py-libp2p

Demonstrates listening on TCP, WebSocket, and QUIC simultaneously,
mirroring go-libp2p's multi-transport architecture.

Usage:
    # Start server (auto-detects free ports on all transports):
    python server.py

    # Start server on specific ports:
    python server.py --tcp-port 4001 --ws-port 4002 --quic-port 4003

    # Start client (copy one of the multiaddrs printed by the server):
    python client.py -d /ip4/127.0.0.1/tcp/4001/p2p/<PEER_ID>
    python client.py -d /ip4/127.0.0.1/tcp/4002/ws/p2p/<PEER_ID>
    python client.py -d /ip4/127.0.0.1/udp/4003/quic/p2p/<PEER_ID>
"""

import argparse
import logging

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.utils.address_validation import find_free_port

# Configure minimal logging — set to DEBUG to trace transport selection
logging.basicConfig(level=logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

ECHO_PROTOCOL = TProtocol("/echo/1.0.0")


async def _echo_handler(stream: INetStream) -> None:
    """Echo handler: read the full message and write it back."""
    try:
        peer_id = stream.muxed_conn.peer_id
        data = await stream.read()
        print(f"  [{peer_id!s:.20}...] echoing {len(data)} bytes")
        await stream.write(data)
        await stream.close()
    except Exception as exc:
        print(f"  Handler error: {exc}")
        try:
            await stream.reset()
        except Exception:
            pass


async def run_server(
    tcp_port: int = 0,
    ws_port: int = 0,
    quic_port: int = 0,
) -> None:
    """
    Listen simultaneously on TCP, WebSocket, and QUIC transports.

    If a port is 0 the OS assigns a free ephemeral port.
    """
    if tcp_port == 0:
        tcp_port = find_free_port()
    if ws_port == 0:
        ws_port = find_free_port()
    if quic_port == 0:
        quic_port = find_free_port()

    # Build listen addresses for all three transports
    listen_addrs = [
        multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{tcp_port}"),       # plain TCP
        multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{ws_port}/ws"),      # WebSocket
        multiaddr.Multiaddr(f"/ip4/0.0.0.0/udp/{quic_port}/quic"),  # QUIC
    ]

    # new_host / new_swarm auto-detects the required transports from listen_addrs.
    # Pass listen_addrs here so the Swarm is built with TCP + WebSocket + QUIC
    # transports pre-registered.  host.run(listen_addrs=...) then just binds
    # the ports — it does not rebuild the transport list.
    host = new_host(key_pair=create_new_key_pair(), listen_addrs=listen_addrs)
    host.set_stream_handler(ECHO_PROTOCOL, _echo_handler)

    print("=== Multi-Transport Echo Server ===\n")
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
            f"\nConnect using any of the following (replace 0.0.0.0 with your IP):\n"
            f"\n  TCP:       python client.py -d /ip4/127.0.0.1/tcp/{tcp_port}/p2p/{peer_id}"
            f"\n  WebSocket: python client.py -d /ip4/127.0.0.1/tcp/{ws_port}/ws/p2p/{peer_id}"
            f"\n  QUIC:      python client.py -d /ip4/127.0.0.1/udp/{quic_port}/quic/p2p/{peer_id}"
        )
        print("\nWaiting for connections… (Ctrl-C to stop)\n")

        await trio.sleep_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-transport echo server (TCP + WebSocket + QUIC)."
    )
    parser.add_argument(
        "--tcp-port", type=int, default=0, help="TCP listen port (0 = auto)"
    )
    parser.add_argument(
        "--ws-port", type=int, default=0, help="WebSocket listen port (0 = auto)"
    )
    parser.add_argument(
        "--quic-port", type=int, default=0, help="QUIC listen port (0 = auto)"
    )
    args = parser.parse_args()
    try:
        trio.run(run_server, args.tcp_port, args.ws_port, args.quic_port)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
