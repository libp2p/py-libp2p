#!/usr/bin/env python3
"""
TLS Client Example

This example demonstrates how to connect to a TLS-enabled py-libp2p host.
It supports both simple echo mode and interactive chat mode.

Usage:
    python example_tls_client.py [--server MULTIADDR] [--mode MODE] [--message MESSAGE]

Examples:
    # Echo mode (default)
    python example_tls_client.py --server /ip4/127.0.0.1/tcp/8000/p2p/QmHash...

"""

import argparse
from datetime import datetime
import sys

import multiaddr
import trio

from libp2p import generate_new_rsa_identity, new_host
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.tls.transport import (
    PROTOCOL_ID as TLS_PROTOCOL_ID,
    TLSTransport,
)
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.utils import get_available_interfaces, get_optimal_binding_address

# Protocol IDs for different services
ECHO_PROTOCOL_ID = TProtocol("/tls-example/1.0.0")  # For backwards compatibility
CHAT_PROTOCOL_ID = TProtocol("/tls-chat/1.0.0")  # For chat functionality


def current_time():
    """Return formatted current time"""
    return datetime.now().strftime("%H:%M:%S")


async def read_data(
    stream,
    max_size: int = 4096,
    timeout_seconds: int = 10,
) -> bytes | None:
    """
    Read data from a stream with a timeout.

    Args:
        stream: The stream to read from
        max_size: Maximum number of bytes to read
        timeout_seconds: Maximum seconds to wait for data

    Returns:
        The data read or None if timeout or error

    """
    try:
        with trio.move_on_after(timeout_seconds):
            response = await stream.read(max_size)
            return response
    except trio.TooSlowError:
        print(f"[{current_time()}] Read timeout after {timeout_seconds} seconds")
        return None
    except Exception as e:
        print(f"[{current_time()}] Error reading from stream: {e}")
        return None


async def run_echo_mode(host, peer_info, message):
    """
    Run the client in echo mode: send a message and receive one response.

    Args:
        host: The libp2p host
        peer_info: PeerInfo object for the server
        message: The message to send

    """
    try:
        print(f"[{current_time()}] Connecting to server: {peer_info.peer_id}")
        print(f"[{current_time()}] Using protocol: {ECHO_PROTOCOL_ID}")

        # Check if we have addresses for the peer
        addrs = host.get_peerstore().addrs(peer_info.peer_id)
        if not addrs:
            # Format message in two parts to avoid line length issues
            msg_prefix = f"[{current_time()}] Warning: No addresses found for peer "
            message = f"{msg_prefix}{peer_info.peer_id}"
            print(message)
        else:
            # Print the number of addresses found
            print(f"[{current_time()}] Found {len(addrs)} address(es) for peer")
            print(message)
        # Open a connection to the server
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                print(f"[{current_time()}] Attempting to open stream...")
                stream = await host.new_stream(peer_info.peer_id, [ECHO_PROTOCOL_ID])
                print(f"[{current_time()}] Stream established successfully")
                break
            except ConnectionRefusedError:
                print(f"[{current_time()}] Connection refused. Is the server running?")
                if retry_count < max_retries - 1:
                    print(f"[{current_time()}] Retrying in 1 second...")
                    await trio.sleep(1)
                else:
                    print(f"[{current_time()}] Maximum retries reached. Giving up.")
                    return
            except Exception as e:
                print(f"[{current_time()}] Connection error: {e}")
                if retry_count < max_retries - 1:
                    print(f"[{current_time()}] Retrying in 1 second...")
                    await trio.sleep(1)
                else:
                    print(f"[{current_time()}] Maximum retries reached. Giving up.")
                    return
            retry_count += 1

        # If we've exhausted all retries without success
        if retry_count >= max_retries:
            print(f"[{current_time()}] Failed to connect after {max_retries} attempts.")
            return

        # Get connection security details
        conn = stream.muxed_conn
        if hasattr(conn, "secured_conn") and hasattr(conn.secured_conn, "tls_version"):
            msg1 = f"[{current_time()}] Connection secured with:"
            msg2 = f"{conn.secured_conn.tls_version}"
            message = f"{msg1} {msg2}"
            print(message)
        else:
            print(f"[{current_time()}] Connection secured with TLS")

        # Send message
        message_bytes = message.encode() if isinstance(message, str) else message
        print(f"[{current_time()}] Sending message: {message_bytes.decode()}")
        await stream.write(message_bytes)

        # Wait for response
        print(f"[{current_time()}] Waiting for response...")
        response = await read_data(stream)

        if response is not None:
            print(f"[{current_time()}] Received response: {response.decode()}")
        else:
            print(f"[{current_time()}] No response received or timed out")

        # Close the stream
        await stream.close()
        print(f"[{current_time()}] Connection closed")

    except Exception as e:
        print(f"[{current_time()}] Error in echo mode: {e}")


async def chat_reader(stream):
    """Read messages from the server and print them."""
    try:
        while True:
            message = await stream.read(4096)
            if not message:
                break
            print(f"{message.decode().strip()}")
    except trio.BrokenResourceError:
        print(f"[{current_time()}] Server disconnected")
    except Exception as e:
        print(f"[{current_time()}] Read error: {e}")


async def chat_writer(stream):
    """Read input from the user and send to the server."""
    try:
        print("Type your messages (Ctrl+D or empty message to exit):")
        while True:
            try:
                line = await trio.to_thread.run_sync(sys.stdin.readline)
                if not line or line.strip() == "":
                    print("Exiting chat...")
                    break

                await stream.write(line.encode())
            except (EOFError, KeyboardInterrupt):
                print("\nExiting chat...")
                break
    except Exception as e:
        print(f"[{current_time()}] Write error: {e}")


async def run_chat_mode(host, peer_info):
    """
    Run the client in chat mode: maintain an open connection for multiple messages.

    Args:
        host: The libp2p host
        peer_info: PeerInfo object for the server

    """
    try:
        print(f"[{current_time()}] Connecting to chat server: {peer_info.peer_id}")

        # Check if we have addresses for the peer in the peerstore
        addrs = host.get_peerstore().addrs(peer_info.peer_id)
        if not addrs:
            # Format message in two parts to avoid line length issues
            msg_prefix = f"[{current_time()}] Warning: No addresses found for peer "
            message = f"{msg_prefix}{peer_info.peer_id}"
            print(message)
        else:
            addr_list = [str(a) for a in addrs]
            print(
                f"[{current_time()}] Found {len(addrs)} address(es) for peer:"
                f" {addr_list}"
            )

        # Try the chat protocol first, fall back to echo if not supported
        protocols = [CHAT_PROTOCOL_ID, ECHO_PROTOCOL_ID]
        print(f"[{current_time()}] Attempting to open stream with protocols")
        print(message)
        stream = await host.new_stream(peer_info.peer_id, protocols)
        print(f"[{current_time()}] Stream established successfully")

        # Get the negotiated protocol
        if hasattr(stream, "protocol"):
            print(f"[{current_time()}] Connected using protocol: {stream.protocol}")

        # Check if we got the chat protocol
        if hasattr(stream, "protocol") and stream.protocol == ECHO_PROTOCOL_ID:
            print(f"[{current_time()}] Warning: Server doesn't support chat protocol.")
            msg1 = f"[{current_time()}] Connected using echo protocol instead."
            msg2 = "Limited functionality."
            message = f"{msg1} {msg2}"
            print(message)
        # Get connection security details
        conn = stream.muxed_conn
        if hasattr(conn, "secured_conn") and hasattr(conn.secured_conn, "tls_version"):
            msg1 = f"[{current_time()}] Connection secured with:"
            msg2 = f"{conn.secured_conn.tls_version}"
            message = f"{msg1} {msg2}"
            print(message)
        else:
            print(f"[{current_time()}] Connection secured with TLS")

        # Start reader and writer tasks
        async with trio.open_nursery() as nursery:
            nursery.start_soon(chat_reader, stream)
            nursery.start_soon(chat_writer, stream)

    except Exception as e:
        print(f"[{current_time()}] Error in chat mode: {e}")


async def run_client(server_addr, mode="echo", message="Hello"):
    """
    Run the TLS client.

    Args:
        server_addr: Multiaddress string of the server
        mode: "echo" or "chat"
        message: The message to send in echo mode

    """
    # Parse server address
    try:
        # Convert string to Multiaddr object first
        maddr = multiaddr.Multiaddr(server_addr)
        peer_info = info_from_p2p_addr(maddr)

        # Connect to server
        print(f"[{current_time()}] Connecting to server with peer ID")
        print(message)
    except Exception as e:
        print(f"[{current_time()}] Error parsing server address: {e}")
        msg1 = f"[{current_time()}] The server address should be in the format:"
        msg2 = "/ip4/127.0.0.1/tcp/8000/p2p/QmPeerID"
        message = f"{msg1} {msg2}"
        print(message)
        return

    # Create a new RSA key pair for this client
    client_key_pair = generate_new_rsa_identity()

    # Create a host with TLS security
    print(f"[{current_time()}] Starting TLS-enabled client...")

    # Create TLS transport with explicit muxer preference
    tls_transport = TLSTransport(client_key_pair, muxers=[MPLEX_PROTOCOL_ID])

    host = new_host(
        key_pair=client_key_pair,
        sec_opt={TLS_PROTOCOL_ID: tls_transport},  # type: ignore
        muxer_opt={MPLEX_PROTOCOL_ID: Mplex},  # type: ignore
    )

    # Add the server's address to the peerstore with a longer TTL
    # First try to extract IP and port components
    try:
        address_components = maddr.value_for_protocol("ip4")
        port_str = maddr.value_for_protocol("tcp")
        if address_components and port_str:
            port = int(port_str) if port_str else 0
            server_maddr = multiaddr.Multiaddr(f"/ip4/{address_components}/tcp/{port}")
            print(f"[{current_time()}] Adding server address to peerstore")
            print(message)
            host.get_peerstore().add_addr(peer_info.peer_id, server_maddr, 3600)
        else:
            raise ValueError("Could not extract IP or port from multiaddr")

        # Also add the original multiaddr to be safe
        print(f"[{current_time()}] Also adding original multiaddr: {maddr}")
        host.get_peerstore().add_addr(peer_info.peer_id, maddr, 3600)
    except Exception as e:
        print(f"[{current_time()}] Warning: Error processing server address: {e}")
        # Try with just the original multiaddr as fallback
        print(f"[{current_time()}] Using original multiaddr as fallback: {maddr}")
        host.get_peerstore().add_addr(peer_info.peer_id, maddr, 3600)
    # Run the host and connect to the server
    async with host.run(listen_addrs=[]):  # Client doesn't need to listen
        client_id = host.get_id()
        print(f"[{current_time()}] Client started with Peer ID: {client_id}")

        if mode == "echo":
            await run_echo_mode(host, peer_info, message)
        elif mode == "chat":
            await run_chat_mode(host, peer_info)
        else:
            print(f"[{current_time()}] Unknown mode: {mode}")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="TLS Client Example")
    parser.add_argument(
        "--server",
        default="/ip4/127.0.0.1/tcp/8000/p2p/QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N",
        help="The multiaddress of the server to connect to",
    )
    parser.add_argument(
        "--mode",
        choices=["echo", "chat"],
        default="echo",
        help="Client mode: echo (default) or chat",
    )
    parser.add_argument(
        "--message",
        default="Hello from TLS client! This message is encrypted.",
        help="The message to send in echo mode",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    trio.run(run_client, args.server, args.mode, args.message)
