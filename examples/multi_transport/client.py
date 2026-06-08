#!/usr/bin/env python3
"""
Multi-Transport Echo Client — py-libp2p

Connects to the multi-transport echo server using whichever transport
is encoded in the supplied multiaddress.

Usage:
    python client.py -d /ip4/127.0.0.1/tcp/4001/p2p/<PEER_ID>
    python client.py -d /ip4/127.0.0.1/tcp/4002/ws/p2p/<PEER_ID>
    python client.py -d /ip4/127.0.0.1/udp/4003/quic/p2p/<PEER_ID>
"""

import argparse
import logging
from pathlib import Path
import sys
from time import sleep

# Ensure local libp2p is used
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr

logging.basicConfig(level=logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

ECHO_PROTOCOL = TProtocol("/echo/1.0.0")


def _detect_transport(maddr_str: str) -> str:
    """Return a human-readable transport name from a multiaddr string."""
    if "/quic" in maddr_str:
        return "QUIC"
    if "/ws" in maddr_str or "/wss" in maddr_str:
        return "WebSocket"
    return "TCP"


async def run_client(
    destination: str, message: bytes = b"hello from py-libp2p!\n"
) -> None:
    """
    Connect to *destination* (a full /p2p/… multiaddr), send *message*, and
    print the echoed reply.

    The client inspects the destination multiaddr to enable the right transport
    in the Swarm's TransportManager before dialing.
    """
    transport_name = _detect_transport(destination)
    print(f"=== Multi-Transport Echo Client ({transport_name}) ===\n")

    maddr = multiaddr.Multiaddr(destination)
    info = info_from_p2p_addr(maddr)

    # Enable the transport that matches the destination address.
    # new_host() must know which transports to register at construction time —
    # the TransportManager is fixed after the Swarm is built.
    enable_quic = transport_name == "QUIC"
    enable_websocket = transport_name == "WebSocket"

    host = new_host(
        key_pair=create_new_key_pair(),
        enable_quic=enable_quic,
        enable_websocket=enable_websocket,
    )

    # Client doesn't listen — pass an empty list.
    async with host.run(listen_addrs=[]):
        print(f"My peer ID : {host.get_id().to_string()}")
        print(f"Connecting : {destination}\n")

        await host.connect(info)
        print(f"Connected  ✓  (transport: {transport_name})")

        stream = await host.new_stream(info.peer_id, [ECHO_PROTOCOL])
        await stream.write(message)
        # Read exactly the number of bytes we sent to avoid deadlocks
        response = await stream.read(len(message))
        await stream.close()

        print(f"Sent : {message!r}")
        print(f"Got  : {response!r}")

        if response == message:
            print("\n✅  Echo verified — round-trip successful!")
        else:
            print("\n❌  Echo mismatch!")
        sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-transport echo client (auto-selects TCP / WebSocket / QUIC)."
    )
    parser.add_argument(
        "-d",
        "--destination",
        required=True,
        type=str,
        help=(
            "Full multiaddr of the server including /p2p/<PEER_ID>, e.g.: "
            "/ip4/127.0.0.1/tcp/4001/p2p/16Uiu2..."
        ),
    )
    parser.add_argument(
        "-m",
        "--message",
        type=str,
        default="hello from py-libp2p!",
        help="Message to echo (default: 'hello from py-libp2p!')",
    )
    args = parser.parse_args()
    try:
        trio.run(run_client, args.destination, args.message.encode())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
