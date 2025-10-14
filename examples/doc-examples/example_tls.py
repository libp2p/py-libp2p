#!/usr/bin/env python3
"""
TLS Server Example

This example demonstrates how to create a TLS-enabled py-libp2p host that accepts
connections and responds to messages from clients. The server will print out its
listen addresses, which can be used by clients to connect.

Usage:
    python example_tls.py [--port PORT]
"""

import argparse
from datetime import datetime

import multiaddr
import trio

from libp2p import generate_new_rsa_identity, new_host
from libp2p.custom_types import TProtocol
from libp2p.security.tls.transport import (
    PROTOCOL_ID as TLS_PROTOCOL_ID,
    TLSTransport,
)
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.utils import get_available_interfaces, get_optimal_binding_address

# Define a protocol ID for our example
PROTOCOL_ID = TProtocol("/tls-example/1.0.0")


async def handle_echo(stream):
    """
    Handle an incoming stream from a client.

    Args:
        stream: The incoming stream

    """
    peer_id = stream.muxed_conn.peer_id
    remote_addr = stream.muxed_conn.remote_multiaddr
    timestamp = datetime.now().strftime("%H:%M:%S")

    print(f"[{timestamp}] Received new stream from peer: {peer_id} at {remote_addr}")

    # Get connection security details if available
    conn = stream.muxed_conn
    if hasattr(conn, "secured_conn") and hasattr(conn.secured_conn, "tls_version"):
        print(f"[{timestamp}] Connection secured with: {conn.secured_conn.tls_version}")

    try:
        # Read the client's message
        message = await stream.read(4096)
        print(f"[{timestamp}] Received message: {message.decode()}")

        # Send a response back
        response = (
            f"Server received your message of length {len(message)}. "
            f"Your message was: {message.decode()}"
        ).encode()
        await stream.write(response)
        print(f"[{timestamp}] Sent response to peer: {peer_id}")
    except Exception as e:
        print(f"[{timestamp}] Error handling stream: {e}")
    finally:
        # Close the stream when done
        await stream.close()
        print(f"[{timestamp}] Closed stream with peer: {peer_id}")


async def main(host_str="0.0.0.0", port=8000) -> None:
    """
    Run a TLS-enabled server that accepts connections and handles messages.

    Args:
        host_str: The host address to listen on (0.0.0.0 for all interfaces)
        port: The port to listen on (0 for random port)

    """
    # Generate a new key pair for this host
    key_pair = generate_new_rsa_identity()

    # Use the new address paradigm to get optimal binding addresses
    if host_str == "0.0.0.0":
        # Use available interfaces for wildcard binding
        listen_addrs = get_available_interfaces(port, "tcp")
    else:
        # Use optimal binding address for specific host
        listen_addrs = [get_optimal_binding_address(port, "tcp")]

    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] Starting TLS-enabled libp2p host...")

    # Create a TLS transport with our key pair and explicit muxer preference
    tls_transport = TLSTransport(key_pair, muxers=[MPLEX_PROTOCOL_ID])

    # Create a host with TLS security transport
    host = new_host(
        key_pair=key_pair,
        sec_opt={TLS_PROTOCOL_ID: tls_transport},
        muxer_opt={MPLEX_PROTOCOL_ID: Mplex},  # Using MPLEX for stream multiplexing
    )

    # Set up a handler for the echo protocol
    host.set_stream_handler(PROTOCOL_ID, handle_echo)

    async with host.run(listen_addrs=listen_addrs):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Host started with Peer ID: {host.get_id()}")

        # Create a connection string with our configured host/port
        peer_id = host.get_id()
        connection_addr = f"/ip4/{host_str}/tcp/{port}/p2p/{peer_id}"

        print(f"Server listening on: {host_str}:{port}")
        print(f"Server peer ID: {peer_id}")

        print(f"\nProtocol: {PROTOCOL_ID}")
        print("Security: TLS 1.3")
        print("Stream Multiplexing: MPLEX")

        print("\nUse example_tls_client.py to connect to this server:")
        print(f"  python example_tls_client.py --server {connection_addr}")

        print("\nTLS is now active. Waiting for connections. Press Ctrl+C to stop.")
        try:
            # Keep the server running until interrupted
            await trio.sleep_forever()
        except KeyboardInterrupt:
            pass

    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] Host shut down cleanly.")


def parse_args():
    parser = argparse.ArgumentParser(description="TLS Server Example")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to listen on")
    parser.add_argument(
        "-p", "--port", type=int, default=8000, help="Port to listen on"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Set up logging if debug is enabled
    if args.debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    trio.run(main, args.host, args.port)
