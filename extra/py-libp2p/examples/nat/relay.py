"""
Circuit Relay v2 Relay Node for NAT Traversal Example.

This module implements a publicly reachable relay node that facilitates
connections between NATed peers using Circuit Relay v2.

Usage:
    python relay.py --port 8000
"""

import argparse
import logging
import os
import sys

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.protocol import (
    PROTOCOL_ID,
    STOP_PROTOCOL_ID,
    CircuitV2Protocol,
)
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.tools.anyio_service import background_trio_service
from libp2p.utils.logging import setup_logging as libp2p_setup_logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("nat-relay")

# Application protocol for testing
EXAMPLE_PROTOCOL_ID = TProtocol("/nat-example/1.0.0")
MAX_READ_LEN = 2**16  # 64KB


async def handle_example_protocol(stream: INetStream) -> None:
    """Handle incoming messages on our example protocol."""
    remote_peer_id = stream.muxed_conn.peer_id
    try:
        remote_addr = stream.get_remote_address()
    except Exception:
        remote_addr = None
    logger.debug(
        "[APP] handle_example_protocol: incoming stream | "
        "remote_peer=%s | remote_addr=%s | protocol=%s",
        remote_peer_id,
        remote_addr,
        getattr(stream, "protocol_id", None),
    )

    try:
        # Read the incoming message
        logger.debug("[APP] waiting to read up to %s bytes from stream", MAX_READ_LEN)
        msg = await stream.read(MAX_READ_LEN)
        if msg:
            logger.info(
                "Received message (%d bytes): %s", len(msg), msg.decode(errors="ignore")
            )

        # Send a response
        local_peer_id = stream.muxed_conn.peer_id
        response = f"Hello! This is relay {local_peer_id}".encode()
        logger.debug("[APP] writing %d bytes to stream", len(response))
        await stream.write(response)
        logger.info("Sent response to %s", remote_peer_id)
    except Exception as e:
        logger.exception("[APP] Error handling stream: %s", e)
    finally:
        try:
            await stream.close()
            logger.debug("[APP] stream closed")
        except Exception:
            logger.debug("[APP] stream close raised, attempting reset")
            try:
                await stream.reset()
            except Exception:
                pass


def generate_fixed_private_key(seed: int | None) -> bytes:
    """Generate a fixed private key from a seed for reproducible peer IDs."""
    import random

    if seed is None:
        # Generate random bytes if no seed provided
        return random.getrandbits(32 * 8).to_bytes(length=32, byteorder="big")

    random.seed(seed)
    return random.getrandbits(32 * 8).to_bytes(length=32, byteorder="big")


async def setup_relay_node(port: int, seed: int | None = None) -> None:
    """Set up and run a relay node."""
    logger.info("Starting relay node for NAT traversal example...")

    # Create host with a fixed key if seed is provided
    key_pair = create_new_key_pair(generate_fixed_private_key(seed) if seed else None)
    logger.debug("[RELAY] created key_pair=%s", type(key_pair).__name__)
    host = new_host(key_pair=key_pair)
    logger.debug("[RELAY] host initialized | peer_id=%s", host.get_id())

    # Configure the relay with resource limits
    limits = RelayLimits(
        duration=3600,  # 1 hour
        data=1024 * 1024 * 100,  # 100 MB
        max_circuit_conns=10,
        max_reservations=5,
    )

    relay_config = RelayConfig(
        roles=RelayRole.HOP | RelayRole.STOP | RelayRole.CLIENT,  # All capabilities
        limits=limits,
    )

    # Initialize the protocol with HOP enabled
    protocol = CircuitV2Protocol(host, limits=limits, allow_hop=True)
    logger.debug(
        "[RELAY] CircuitV2Protocol initialized | allow_hop=%s | "
        "limits(duration=%s,data=%s,max_circuit_conns=%s,max_reservations=%s)",
        True,
        limits.duration,
        limits.data,
        limits.max_circuit_conns,
        limits.max_reservations,
    )

    # Start the host
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run(listen_addrs=[listen_addr]):
        # Print information about this node
        peer_id = host.get_id()
        logger.info(f"Relay node started with ID: {peer_id}")

        addrs = host.get_addrs()
        for addr in addrs:
            logger.info(f"Listening on: {addr}")

        # Register protocol handlers
        logger.debug("[RELAY] registering stream handlers")
        host.set_stream_handler(EXAMPLE_PROTOCOL_ID, handle_example_protocol)
        host.set_stream_handler(PROTOCOL_ID, protocol._handle_hop_stream)
        host.set_stream_handler(STOP_PROTOCOL_ID, protocol._handle_stop_stream)
        logger.debug("[RELAY] protocol handlers registered")

        # Start the relay protocol service
        async with background_trio_service(protocol):
            logger.info("Circuit relay protocol started")

            # Create and register the transport
            CircuitV2Transport(host, protocol, relay_config)
            logger.info(
                "Circuit relay transport initialized | "
                "enable_hop=%r enable_stop=%r enable_client=%r",
                relay_config.enable_hop,
                relay_config.enable_stop,
                relay_config.enable_client,
            )

            print("\n" + "=" * 60)
            print("Relay node is running!")
            print("=" * 60)
            print(f"Peer ID: {peer_id}")
            print(f"Address: {addrs[0]}")
            print("\nUse this address to connect listener and dialer nodes.")
            print("Press Ctrl+C to exit\n")

            # Keep the relay running
            await trio.sleep_forever()


def main() -> None:
    """Parse arguments and run the relay node."""
    parser = argparse.ArgumentParser(
        description="Circuit Relay v2 Relay Node for NAT Traversal"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducible peer IDs",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Set log level and libp2p structured logging
    if args.debug:
        # Enable verbose console logs
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("libp2p").setLevel(logging.DEBUG)
        # Also enable libp2p file+console logging via env control, if not set
        os.environ.setdefault("LIBP2P_DEBUG", "DEBUG")
        try:
            libp2p_setup_logging()
            logger.debug("libp2p logging initialized via utils.logging.setup_logging")
        except Exception as e:
            logger.debug(
                "libp2p logging setup failed: %s — continuing with basicConfig", e
            )

    try:
        trio.run(setup_relay_node, args.port, args.seed)
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
