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
    tls-demo [--port PORT] [--seed SEED]

The server will print its listening addresses with peer ID. Use these addresses
to connect clients for interactive bidirectional chat sessions.

Example:
    tls-demo -p 8000

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
from libp2p.host.ping import (
    ID as PING_PROTOCOL_ID,
    handle_ping,
)
from libp2p.network.stream.exceptions import (
    StreamEOF,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.id import (
    ID,
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

# Configure debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("multiaddr").setLevel(logging.DEBUG)
logging.getLogger("libp2p").setLevel(logging.DEBUG)

PROTOCOL_ID = TProtocol("/bidirectional-chat/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def _bidirectional_chat_handler(stream: INetStream) -> None:
    logger = logging.getLogger(__name__)
    peer_id = stream.muxed_conn.peer_id.to_string()
    peer_display = f"{peer_id[:8]}..."
    logger.debug(f"New chat session with peer {peer_id}, stream: {stream}")
    print(f"Chat session started with {peer_display}")

    async def receive_messages():
        """Receive and display client messages."""
        try:
            while True:
                logger.debug(f"Waiting for message from {peer_display}...")
                data = await stream.read(MAX_READ_LEN)
                if not data:
                    logger.debug(f"Received empty data from {peer_display}")
                    break

                text = data.decode("utf-8").strip()
                logger.debug(
                    f"Received {len(data)} bytes from {peer_display}: {text[:50]}..."
                )
                if text.lower() in ["quit", "exit", "bye"]:
                    logger.debug(f"Client {peer_display} requested to end session")
                    print(f"Client {peer_display} ended session")
                    break

                print(f"Client {peer_display}: {text}")

        except StreamEOF:
            logger.debug(f"Stream EOF from {peer_display}")
            print(f"Client {peer_display} disconnected")
        except Exception as e:
            logger.exception(f"Receive error from {peer_display}: {e}")
            print(f"Receive error from {peer_display}: {e}")

    async def send_messages():
        """Send server messages to client."""
        try:
            print(f"Server chatting with {peer_display} (type 'quit' to end)")
            while True:
                try:
                    # Use trio's run_sync_in_worker_thread to avoid blocking loop
                    message = await trio.to_thread.run_sync(input, "\nServer: ")
                    message = message.strip()

                    if not message:
                        continue

                    if message.lower() in ["quit", "exit", "bye"]:
                        print("Server ending session")
                        await stream.write(b"Server ended the session\n")
                        break

                    await stream.write(f"{message}\n".encode())
                    logger.debug(f"Sent message to {peer_display}: {message[:50]}...")

                except (EOFError, KeyboardInterrupt):
                    logger.debug("Server input interrupted")
                    print("Server input interrupted")
                    break
                except Exception as e:
                    logger.exception(f"Send error: {e}")
                    print(f"Send error: {e}")
                    break

        except Exception as e:
            logger.exception(f"Send task error: {e}")
            print(f"Send task error: {e}")

    try:
        async with trio.open_nursery() as nursery:
            logger.debug(f"Starting bidirectional chat tasks for {peer_display}")
            nursery.start_soon(receive_messages)
            nursery.start_soon(send_messages)
    except KeyboardInterrupt:
        logger.debug(f"Chat session with {peer_display} interrupted by user")
        print(f"Chat session with {peer_display} interrupted")
    except Exception as e:
        logger.exception(f"Chat handler error: {e}")
        print(f"Chat handler error: {e}")
    finally:
        try:
            logger.debug(f"Closing stream for {peer_display}")
            await stream.close()
        except Exception:
            logger.exception(f"Error closing stream for {peer_display}")
            pass
        logger.debug(f"Session with {peer_display} closed")
        print(f"Session with {peer_display} closed")


async def run(port: int, seed: int | None = None) -> None:
    logger = logging.getLogger(__name__)

    if port <= 0:
        port = find_free_port()
        logger.debug(f"Auto-selected free port: {port}")
    else:
        logger.debug(f"Using specified port: {port}")
    listen_addr = get_available_interfaces(port)
    logger.debug(f"Listen addresses: {listen_addr}")

    if seed:
        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
        logger.debug(f"Using seed {seed} for key generation")
    else:
        secret = secrets.token_bytes(32)
        logger.debug("Generated random secret for key pair")

    key_pair = create_new_key_pair(secret)
    peer_id = ID.from_pubkey(key_pair.public_key)
    logger.debug(f"Created key pair, peer ID: {peer_id.to_string()}")

    # Create TLS security transport
    tls_transport = TLSTransport(key_pair)
    logger.debug("Created TLS transport")

    # Create security options with TLS
    sec_opt = {TLS_PROTOCOL_ID: tls_transport}
    logger.debug(f"Configured security options with TLS protocol: {TLS_PROTOCOL_ID}")

    host = new_host(key_pair=key_pair, sec_opt=sec_opt)
    logger.debug("Created libp2p host")
    async with host.run(listen_addrs=listen_addr), trio.open_nursery() as nursery:
        logger.debug(f"Host started, listening on: {listen_addr}")
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
        logger.debug("Started peerstore cleanup task")

        server_peer_id = host.get_id().to_string()
        print(f"I am {server_peer_id}")
        logger.debug(f"Server peer ID: {server_peer_id}")

        host.set_stream_handler(PROTOCOL_ID, _bidirectional_chat_handler)
        logger.debug(f"Registered stream handler for protocol: {PROTOCOL_ID}")

        # Register ping handler for ping mode
        host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)
        logger.debug(f"Registered ping handler for protocol: {PING_PROTOCOL_ID}")

        # Print all listen addresses with peer ID (JS parity)
        print("TLS-enabled listener ready, listening on:\n")
        for addr in listen_addr:
            full_addr = f"{addr}/p2p/{server_peer_id}"
            print(full_addr)
            logger.debug(f"Listening on: {full_addr}")

        # Get optimal address for display
        optimal_addr = get_optimal_binding_address(port)
        optimal_addr_with_peer = f"{optimal_addr}/p2p/{server_peer_id}"
        logger.debug(f"Optimal address: {optimal_addr_with_peer}")

        print(
            "\nRun this from the same folder in another console:\n\n"
            f"tls-client-demo --server {optimal_addr_with_peer} "
            "--mode chat\n"
        )
        print("Waiting for incoming TLS connections...")
        logger.debug("Server ready, waiting for connections...")
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.debug("Server shutdown requested by user")
            print("\nServer shutdown requested...")
            raise


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
    logger = logging.getLogger(__name__)
    logger.debug(f"Starting TLS server with port={args.port}, seed={args.seed}")
    try:
        trio.run(run, args.port, args.seed)
    except KeyboardInterrupt:
        logger.debug("TLS server shutdown by user")
        print("\nTLS server shutting down gracefully...")
    except Exception as e:
        logger.exception(f"Unexpected error in TLS server: {e}")
        print(f"\nUnexpected error in TLS server: {e}")
        raise


if __name__ == "__main__":
    main()
