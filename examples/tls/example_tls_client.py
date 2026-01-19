#!/usr/bin/env python3
"""
TLS-Enabled Py-libp2p Bidirectional Chat Client Example

This example demonstrates how to connect to a TLS-enabled py-libp2p host and
engage in true bidirectional chat sessions where both client and server can
send and receive messages simultaneously.

Features:
- TLS 1.3 encryption for secure client-server communication
- Two communication modes: single message echo and full-duplex bidirectional chat
- Automatic certificate verification and peer identity validation
- Graceful error handling and connection management
- Concurrent send/receive operations for real-time chat experience
- Both parties can initiate messages at any time

Usage:
    python example_tls_client.py --server MULTIADDR [--mode MODE] [--message MESSAGE]

Modes:
- echo: Send a single message and receive the echo response (default)
- chat: Full-duplex bidirectional chat where both parties can send/receive
  simultaneously

Examples:
    # Echo mode (default)
    python example_tls_client.py --server \
        /ip4/127.0.0.1/tcp/8000/p2p/12D3KooWAbcd1234567890efghijklmnop

    # Bidirectional chat mode - real-time conversation
    python example_tls_client.py --server \
        /ip4/127.0.0.1/tcp/8000/p2p/12D3KooWAbcd1234567890efghijklmnop \
        --mode chat

    # Custom message in echo mode
    python example_tls_client.py --server \
        /ip4/127.0.0.1/tcp/8000/p2p/12D3KooWAbcd1234567890efghijklmnop \
        --message "Hello TLS!"

"""

import argparse
import logging
import random
import secrets
import sys

import multiaddr
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
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.security.tls import (
    PROTOCOL_ID as TLS_PROTOCOL_ID,
    TLSTransport,
)

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

if sys.version_info >= (3, 11):
    from builtins import ExceptionGroup
else:
    from exceptiongroup import ExceptionGroup

PROTOCOL_ID = TProtocol("/bidirectional-chat/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def echo_mode(host, server_maddr: str, message: str) -> None:
    """Send a single message and receive echo response."""
    stream = None
    try:
        maddr = multiaddr.Multiaddr(server_maddr)
        info = info_from_p2p_addr(maddr)

        print(f"Connecting to {server_maddr}...")
        await host.connect(info)

        print("Opening stream...")
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

        print(f"Sending: {message}")
        await stream.write(message.encode("utf-8"))

        print("Waiting for response...")
        response = await stream.read(MAX_READ_LEN)

        print(f"Received: {response.decode('utf-8')}")

    except (KeyboardInterrupt, ExceptionGroup) as e:
        # Handle KeyboardInterrupt directly or within ExceptionGroup
        if isinstance(e, KeyboardInterrupt):
            print("\nEcho mode interrupted")
            raise
        elif isinstance(e, ExceptionGroup):
            if any(isinstance(exc, KeyboardInterrupt) for exc in e.exceptions):
                print("\nEcho mode interrupted")
                raise
        raise
    except Exception as e:
        print(f"Error in echo mode: {e}")
        raise
    finally:
        if stream:
            try:
                await stream.close()
            except Exception:
                pass  # Best effort cleanup


async def chat_mode(host, server_maddr: str) -> None:
    """Bidirectional chat with server."""
    stream = None
    try:
        maddr = multiaddr.Multiaddr(server_maddr)
        info = info_from_p2p_addr(maddr)

        print("Connecting to server...")
        await host.connect(info)

        print("Opening chat stream...")
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

        print("Connected! Chat bidirectionally (Ctrl+C to quit)")
        print("-" * 50)

        async def receive_messages():
            """Receive and display server messages."""
            if not stream:
                return
            try:
                while True:
                    data = await stream.read(MAX_READ_LEN)
                    if not data:
                        break

                    text = data.decode("utf-8").strip()
                    if "ended the session" in text.lower():
                        print(f"\nServer: {text}")
                        break

                    print(f"\nServer: {text}")

            except StreamEOF:
                print("Server disconnected")
            except Exception as e:
                print(f"Receive error: {e}")

        async def send_messages():
            """Send client messages to server."""
            if not stream:
                return
            try:
                while True:
                    try:
                        message = await trio.to_thread.run_sync(input, "\nYou: ")
                        message = message.strip()

                        if not message:
                            continue

                        if message.lower() in ["quit", "exit", "bye"]:
                            print("Ending session")
                            await stream.write(message.encode("utf-8"))
                            break

                        await stream.write(message.encode("utf-8"))

                    except (EOFError, KeyboardInterrupt):
                        print("Ending session")
                        try:
                            await stream.write(b"quit")
                        except Exception:
                            pass
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
        except (KeyboardInterrupt, ExceptionGroup) as e:
            # Handle KeyboardInterrupt directly or within ExceptionGroup
            if isinstance(e, KeyboardInterrupt):
                print("\nChat interrupted")
            elif isinstance(e, ExceptionGroup):
                if any(isinstance(exc, KeyboardInterrupt) for exc in e.exceptions):
                    print("\nChat interrupted")
                else:
                    raise
            else:
                raise
        except Exception as e:
            print(f"Chat error: {e}")
            raise

    except (KeyboardInterrupt, ExceptionGroup) as e:
        # Handle KeyboardInterrupt directly or within ExceptionGroup
        if isinstance(e, KeyboardInterrupt):
            print("\nChat session interrupted")
        elif isinstance(e, ExceptionGroup):
            if any(isinstance(exc, KeyboardInterrupt) for exc in e.exceptions):
                print("\nChat session interrupted")
            else:
                raise
        else:
            raise
    except Exception as e:
        print(f"Chat error: {e}")
        raise
    finally:
        if stream:
            try:
                await stream.close()
            except Exception:
                pass
        print("Disconnected from server")


async def run(server: str, mode: str, message: str, seed: int | None = None) -> None:
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

    try:
        async with host.run(listen_addrs=[]):
            print(f"TLS-enabled client started. Peer ID: {host.get_id().to_string()}")

            if mode == "echo":
                if not message:
                    message = "Hello from TLS client!"
                await echo_mode(host, server, message)
            elif mode == "chat":
                await chat_mode(host, server)
            else:
                print(f"Unknown mode: {mode}")
                return
    except (KeyboardInterrupt, ExceptionGroup) as e:
        # Handle KeyboardInterrupt directly or within ExceptionGroup
        if isinstance(e, KeyboardInterrupt):
            print("\nClient shutdown requested...")
            raise
        elif isinstance(e, ExceptionGroup):
            if any(isinstance(exc, KeyboardInterrupt) for exc in e.exceptions):
                print("\nClient shutdown requested...")
                raise
        raise


def main() -> None:
    description = """
    This example demonstrates how to connect to a TLS-enabled py-libp2p host.
    It supports both simple echo mode and interactive chat mode.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--server",
        required=True,
        help="Server multiaddr to connect to "
        "(e.g. /ip4/127.0.0.1/tcp/8000/p2p/12D3KooWAbcd1234567890efghijklmnop)",
    )
    parser.add_argument(
        "--mode",
        choices=["echo", "chat"],
        default="echo",
        help="Connection mode: echo (default) or chat",
    )
    parser.add_argument(
        "--message",
        default="",
        help="Message to send in echo mode (default: 'Hello from TLS client!')",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help="provide a seed to the random number generator "
        "(e.g. to fix peer IDs across runs)",
    )
    args = parser.parse_args()

    try:
        trio.run(run, args.server, args.mode, args.message, args.seed)
    except KeyboardInterrupt:
        print("\nTLS client shutting down gracefully...")
    except Exception as e:
        print(f"\nUnexpected error in TLS client: {e}")
        raise


if __name__ == "__main__":
    main()
