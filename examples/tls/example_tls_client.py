#!/usr/bin/env python3
r"""
TLS-Enabled Py-libp2p Bidirectional Chat Client Example

This example demonstrates how to connect to a TLS-enabled py-libp2p host and
engage in true bidirectional chat sessions where both client and server can
send and receive messages simultaneously.

Features:

- TLS 1.3 encryption for secure client-server communication
- Three communication modes:
  - single message echo,
  - full-duplex bidirectional chat, and
  - ping latency testing
- Automatic certificate verification and peer identity validation
- Graceful error handling and connection management
- Concurrent send/receive operations for real-time chat experience

Usage::

    tls-client-demo --server MULTIADDR [--mode MODE] [--message MESSAGE] [--count COUNT]

Modes:

- echo: Send a single message and receive the echo response (default)
- chat: Both client and server can send/receive simultaneously
- ping: Send ping requests and measure round-trip time

Examples::

    # Echo mode (default)
    tls-client-demo --server /ip4/127.0.0.1/tcp/8000/p2p/12D3Koo....

    # Bidirectional chat mode - real-time conversation
    tls-client-demo --server /ip4/127.0.0.1/tcp/8000/p2p/12D3Koo....
    --mode chat

    # Custom message in echo mode
    tls-client-demo --server /ip4/127.0.0.1/tcp/8000/p2p/12D3Koo....
    --message "Hello TLS!"

    # Ping mode - test latency
    tls-client-demo --server /ip4/127.0.0.1/tcp/8000/p2p/12D3Koo....
    --mode ping --count 10

"""

import argparse
import logging
import random
import secrets
import time

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.ping import (
    ID as PING_PROTOCOL_ID,
    PING_LENGTH,
)
from libp2p.network.stream.exceptions import StreamEOF
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.tls import (
    PROTOCOL_ID as TLS_PROTOCOL_ID,
    TLSTransport,
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


async def echo_mode(host, server_maddr: str, message: str) -> None:
    """Send a single message and receive echo response."""
    logger = logging.getLogger(__name__)
    stream = None
    try:
        maddr = multiaddr.Multiaddr(server_maddr)
        info = info_from_p2p_addr(maddr)

        logger.debug(f"Parsed multiaddr: {maddr}, peer_id: {info.peer_id}")
        print(f"Connecting to {server_maddr}...")
        await host.connect(info)
        logger.debug(f"Successfully connected to peer {info.peer_id}")

        print("Opening stream...")
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])
        logger.debug(f"Stream opened: {stream}")

        print(f"Sending: {message}")
        await stream.write(message.encode("utf-8"))
        logger.debug(f"Sent {len(message)} bytes")

        print("Waiting for response...")
        response = await stream.read(MAX_READ_LEN)
        logger.debug(f"Received {len(response)} bytes")

        print(f"Received: {response.decode('utf-8')}")

    except KeyboardInterrupt:
        logger.debug("Echo mode interrupted by user")
        print("\nEcho mode interrupted")
        raise
    except Exception as exc:
        logger.exception("Error in echo mode: %s", exc, exc_info=True)
        print(f"Error in echo mode: {exc}")
        raise
    finally:
        if stream:
            try:
                await stream.close()
            except Exception:
                pass  # Best effort cleanup


async def chat_mode(host, server_maddr: str) -> None:
    """Bidirectional chat with server."""
    logger = logging.getLogger(__name__)
    stream = None
    try:
        maddr = multiaddr.Multiaddr(server_maddr)
        info = info_from_p2p_addr(maddr)

        logger.debug(f"Parsed multiaddr: {maddr}, peer_id: {info.peer_id}")
        print("Connecting to server...")
        await host.connect(info)
        logger.debug(f"Successfully connected to peer {info.peer_id}")

        print("Opening chat stream...")
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])
        logger.debug(f"Chat stream opened: {stream}")

        print("Connected! Chat bidirectionally (Ctrl+C to quit)")
        print("-" * 50)

        async def receive_messages():
            """Receive and display server messages."""
            if not stream:
                return
            try:
                while True:
                    logger.debug("Waiting for server message...")
                    data = await stream.read(MAX_READ_LEN)
                    if not data:
                        logger.debug("Received empty data, ending receive loop")
                        break

                    text = data.decode("utf-8").strip()
                    logger.debug("Received %d bytes: %s...", len(data), text[:50])
                    if "ended the session" in text.lower():
                        print(f"\nServer: {text}")
                        break

                    print(f"\nServer: {text}")

            except StreamEOF:
                logger.debug("Stream EOF received from server")
                print("Server disconnected")
            except Exception as exc:
                logger.exception("Receive error: %s", exc, exc_info=True)
                print(f"Receive error: {exc}")

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
                        logger.debug("Sent message: %s...", message[:50])

                    except (EOFError, KeyboardInterrupt):
                        logger.debug("Input interrupted, ending session")
                        print("Ending session")
                        try:
                            await stream.write(b"quit")
                        except Exception:
                            pass
                        break
                    except Exception as exc:
                        logger.exception("Send error: %s", exc, exc_info=True)
                        print(f"Send error: {exc}")
                        break

            except Exception as exc:
                logger.exception("Send task error: %s", exc, exc_info=True)
                print(f"Send task error: {exc}")

        try:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(receive_messages)
                nursery.start_soon(send_messages)
        except KeyboardInterrupt:
            print("\nChat interrupted")
        except Exception as exc:
            print(f"Chat error: {exc}")
            raise

    except KeyboardInterrupt:
        logger.debug("Chat session interrupted by user")
        print("\nChat session interrupted")
    except Exception as exc:
        logger.exception("Chat error: %s", exc, exc_info=True)
        print(f"Chat error: {exc}")
        raise
    finally:
        if stream:
            try:
                await stream.close()
            except Exception:
                pass
        print("Disconnected from server")


async def ping_mode(host, server_maddr: str, count: int) -> None:
    """Send ping requests and measure round-trip time."""
    logger = logging.getLogger(__name__)
    stream = None
    try:
        maddr = multiaddr.Multiaddr(server_maddr)
        info = info_from_p2p_addr(maddr)

        logger.debug(f"Parsed multiaddr: {maddr}, peer_id: {info.peer_id}")
        print(f"Connecting to {server_maddr}...")
        await host.connect(info)
        logger.debug(f"Successfully connected to peer {info.peer_id}")

        print("Opening ping stream...")
        stream = await host.new_stream(info.peer_id, [PING_PROTOCOL_ID])
        logger.debug(f"Ping stream opened: {stream}")

        print(f"Pinging server ({count} requests)...")
        print("-" * 50)

        rtts = []
        for i in range(count):
            ping_bytes = secrets.token_bytes(PING_LENGTH)
            before = time.time()

            await stream.write(ping_bytes)
            logger.debug("Sent ping #%d", i + 1)

            pong_bytes = await stream.read(PING_LENGTH)
            rtt_ms = (time.time() - before) * 1000
            rtts.append(rtt_ms)

            if ping_bytes != pong_bytes:
                logger.warning("Invalid pong response")
                print(f"Ping #{i + 1}: ERROR - Invalid response")
            else:
                print(f"Ping #{i + 1}: {rtt_ms:.2f} ms")

        if rtts:
            avg_rtt = sum(rtts) / len(rtts)
            min_rtt = min(rtts)
            max_rtt = max(rtts)
            print("-" * 50)
            print(
                f"Statistics: min={min_rtt:.2f} ms, max={max_rtt:.2f} ms, "
                f"avg={avg_rtt:.2f} ms"
            )

    except KeyboardInterrupt:
        logger.debug("Ping mode interrupted by user")
        print("\nPing interrupted")
        raise
    except Exception as exc:
        logger.exception("Error in ping mode: %s", exc, exc_info=True)
        print(f"Error in ping mode: {exc}")
        raise
    finally:
        if stream:
            try:
                await stream.close()
            except Exception:
                pass  # Best effort cleanup


async def run(
    server: str,
    mode: str,
    message: str,
    count: int,
    seed: int | None = None,
) -> None:
    logger = logging.getLogger(__name__)
    if seed is not None:
        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
        logger.debug("Using seed %d for key generation", seed)
    else:
        secret = secrets.token_bytes(32)
        logger.debug("Generated random secret for key pair")

    key_pair = create_new_key_pair(secret)
    peer_id = ID.from_pubkey(key_pair.public_key)
    logger.debug("Created key pair, peer ID: %s", peer_id.to_string())

    # Create TLS security transport
    tls_transport = TLSTransport(key_pair)
    logger.debug("Created TLS transport")

    # Create security options with TLS
    sec_opt = {TLS_PROTOCOL_ID: tls_transport}
    logger.debug("Configured security options with TLS protocol: %s", TLS_PROTOCOL_ID)

    host = new_host(key_pair=key_pair, sec_opt=sec_opt)
    logger.debug("Created libp2p host")

    try:
        async with host.run(listen_addrs=[]):
            peer_id_str = host.get_id().to_string()
            logger.debug("Host started, listening on: %s", [])
            print(f"TLS-enabled client started. Peer ID: {peer_id_str}")

            if mode == "echo":
                msg = message or "Hello from TLS client!"
                logger.debug("Starting echo mode with message: %s", msg)
                await echo_mode(host, server, msg)
            elif mode == "chat":
                logger.debug("Starting chat mode")
                await chat_mode(host, server)
            elif mode == "ping":
                logger.debug("Starting ping mode with count: %d", count)
                await ping_mode(host, server, count)
            else:
                logger.warning("Unknown mode: %s", mode)
                print(f"Unknown mode: {mode}")
                return
    except KeyboardInterrupt:
        logger.debug("Client shutdown requested by user")
        print("\nClient shutdown requested...")
        raise


def main() -> None:
    description = (
        "This example demonstrates how to connect to a TLS-enabled py-libp2p host.\n"
        "It supports echo mode, chat mode, and ping mode for latency testing."
    )
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--server",
        required=True,
        help=(
            "Server multiaddr to connect to "
            "(e.g. /ip4/127.0.0.1/tcp/8000/p2p/12D3Koo....)"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["echo", "chat", "ping"],
        default="echo",
        help="Connection mode: echo (default), chat, or ping",
    )
    parser.add_argument(
        "--message",
        default="",
        help="Message to send in echo mode (default: 'Hello from TLS client!')",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Number of ping requests to send (default: 5, only used in ping mode)",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help=(
            "provide a seed to the random number generator "
            "(e.g. to fix peer IDs across runs)"
        ),
    )
    args = parser.parse_args()

    try:
        trio.run(run, args.server, args.mode, args.message, args.count, args.seed)
    except KeyboardInterrupt:
        print("\nTLS client shutting down gracefully...")
    except Exception as exc:
        print(f"\nUnexpected error in TLS client: {exc}")
        raise


if __name__ == "__main__":
    main()
