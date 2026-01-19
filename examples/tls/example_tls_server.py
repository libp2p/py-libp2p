#!/usr/bin/env python3
"""
TLS-Enabled Py-libp2p Bidirectional Chat Server Example

This example demonstrates how to create a TLS-enabled py-libp2p host that acts as
a bidirectional chat server. The server listens for incoming TLS connections and
engages in full-duplex chat sessions where both server and client can send messages
simultaneously.

Features:
- TLS 1.3 encryption for secure peer-to-peer communication
- Self-signed certificates with embedded peer identities
- True bidirectional chat with concurrent send/receive
- Automatic peer ID verification during TLS handshake
- Graceful handling of chat session lifecycle
- Server can initiate messages to clients

Usage:
    python example_tls_server.py [--port PORT] [--seed SEED]

The server will print its listening addresses with peer ID. Use these addresses
to connect clients for interactive bidirectional chat sessions.

Example:
    python example_tls_server.py -p 8000

"""

import argparse
import logging
import random
import secrets

import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.exceptions import (
    StreamEOF,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.security.tls import (
    PROTOCOL_ID as TLS_PROTOCOL_ID,
    TLSTransport,
)
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
)

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PROTOCOL_ID = TProtocol("/bidirectional-chat/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def _bidirectional_chat_handler(stream: INetStream) -> None:
    peer_id = stream.muxed_conn.peer_id.to_string()
    peer_display = f"{peer_id[:8]}..."
    print(f"Chat session started with {peer_display}")

    async def receive_messages():
        """Receive and display client messages."""
        try:
            while True:
                data = await stream.read(MAX_READ_LEN)
                if not data:
                    break

                text = data.decode("utf-8").strip()
                if text.lower() in ["quit", "exit", "bye"]:
                    print(f"Client {peer_display} ended session")
                    break

                print(f"Client {peer_display}: {text}")

        except StreamEOF:
            print(f"Client {peer_display} disconnected")
        except Exception as e:
            print(f"Receive error from {peer_display}: {e}")

    async def send_messages():
        """Send server messages to client."""
        try:
            print(f"Server chatting with {peer_display} (type 'quit' to end)")
            while True:
                try:
                    message = await trio.to_thread.run_sync(input, "\nServer: ")
                    message = message.strip()

                    if not message:
                        continue

                    if message.lower() in ["quit", "exit", "bye"]:
                        print("Server ending session")
                        await stream.write(b"Server ended the session\n")
                        break

                    await stream.write(f"{message}\n".encode())

                except (EOFError, KeyboardInterrupt):
                    print("Server input interrupted")
                    break
                except Exception as e:
                    print(f"Send error: {e}")
                    break

        except Exception as e:
            print(f"Send task error: {e}")

    try:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(receive_messages)
            nursery.start_soon(send_messages)
    except Exception as e:
        print(f"Chat handler error: {e}")
    finally:
        try:
            await stream.close()
        except Exception:
            pass
        print(f"Session with {peer_display} closed")


async def run(port: int, seed: int | None = None) -> None:
    if port <= 0:
        port = find_free_port()
    listen_addr = get_available_interfaces(port)

    if seed:
        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        secret = secrets.token_bytes(32)

    key_pair = create_new_key_pair(secret)

    # Create TLS security transport
    tls_transport = TLSTransport(key_pair)

    # Create security options with TLS
    sec_opt = {TLS_PROTOCOL_ID: tls_transport}

    host = new_host(key_pair=key_pair, sec_opt=sec_opt)
    async with host.run(listen_addrs=listen_addr), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        print(f"I am {host.get_id().to_string()}")

        host.set_stream_handler(PROTOCOL_ID, _bidirectional_chat_handler)

        # Print all listen addresses with peer ID (JS parity)
        print("TLS-enabled listener ready, listening on:\n")
        peer_id = host.get_id().to_string()
        for addr in listen_addr:
            print(f"{addr}/p2p/{peer_id}")

        # Get optimal address for display
        optimal_addr = get_optimal_binding_address(port)
        optimal_addr_with_peer = f"{optimal_addr}/p2p/{peer_id}"

        print(
            "\nRun this from the same folder in another console:\n\n"
            f"python example_tls_client.py --server {optimal_addr_with_peer} "
            "--mode chat\n"
        )
        print("Waiting for incoming TLS connections...")
        await trio.sleep_forever()


def main() -> None:
    description = """
    This example demonstrates how to create a TLS-enabled py-libp2p host that accepts
    connections and responds to messages from clients. The server will print out its
    listen addresses, which can be used by clients to connect.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port number")
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help="provide a seed to the random number generator "
        "(e.g. to fix peer IDs across runs)",
    )
    args = parser.parse_args()
    try:
        trio.run(run, args.port, args.seed)
    except KeyboardInterrupt:
        print("\nTLS server shutting down gracefully...")
    except Exception as e:
        print(f"\nUnexpected error in TLS server: {e}")
        raise


if __name__ == "__main__":
    main()
