r"""
NAT Traversal Listener Node Example.

This module implements a NAT'd peer that:
- Advertises via a Circuit Relay v2 relay
- Supports DCUtR (Direct Connection Upgrade through Relay) for hole punching
- Uses AutoNAT to detect and report reachability status
- Accepts incoming connections via relay and supports direct upgrades

Usage:
    python listener.py --port 8001 \\
        --relay-addr /ip4/127.0.0.1/tcp/8000/p2p/RELAY_PEER_ID
"""

import argparse
import logging
import os
import sys
from typing import cast

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.autonat import AutoNATService, AutoNATStatus
from libp2p.host.autonat.autonat import AUTONAT_PROTOCOL_ID
from libp2p.host.basic_host import BasicHost
from libp2p.network.stream.net_stream import INetStream, NetStream
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.dcutr import DCUtRProtocol
from libp2p.relay.circuit_v2.discovery import RelayDiscovery
from libp2p.relay.circuit_v2.protocol import (
    PROTOCOL_ID,
    STOP_PROTOCOL_ID,
    CircuitV2Protocol,
)
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.tools.async_service import background_trio_service
from libp2p.utils.logging import setup_logging as libp2p_setup_logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("nat-listener")

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

    # Check if connection is direct or relayed
    is_direct = False
    try:
        # raw_conn is implementation-specific, not in IMuxedConn interface
        conn = stream.muxed_conn.raw_conn  # type: ignore[attr-defined]
        addrs = conn.get_transport_addresses()
        if addrs:
            is_direct = any(not str(addr).startswith("/p2p-circuit") for addr in addrs)
        else:
            # If no addresses, check connection string or assume relayed
            # In local testing, connections might not have addresses in peerstore
            # Check if it's a circuit connection by inspecting the connection
            conn_str = str(conn)
            if "/p2p-circuit" in conn_str:
                is_direct = False
            else:
                # Can't determine, default to relayed for safety
                is_direct = False
    except Exception as e:
        logger.debug("Could not determine connection type: %s", str(e))
        # Default to relayed if we can't determine
        is_direct = False

    connection_type = "DIRECT" if is_direct else "RELAYED"
    logger.info(
        "[APP] Received connection from %s via %s connection | remote_addr=%s",
        remote_peer_id,
        connection_type,
        remote_addr,
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
        response_msg = (
            f"Hello! This is listener {local_peer_id} (via {connection_type})"
        )
        response = response_msg.encode()
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


def get_autonat_status_string(status: int) -> str:
    """Convert AutoNAT status to human-readable string."""
    if status == AutoNATStatus.PUBLIC:
        return "PUBLIC"
    elif status == AutoNATStatus.PRIVATE:
        return "PRIVATE"
    else:
        return "UNKNOWN"


async def log_autonat_status(
    autonat_service: AutoNATService, interval: float = 5.0
) -> None:
    """Periodically log AutoNAT status."""
    while True:
        await trio.sleep(interval)
        status = autonat_service.get_status()
        status_str = get_autonat_status_string(status)
        logger.info(f"[AutoNAT] Reachability status: {status_str}")


async def setup_listener_node(
    port: int, relay_addr: str, seed: int | None = None
) -> None:
    """Set up and run a listener node behind NAT."""
    logger.info("Starting listener node (behind NAT)...")

    # Create host with a fixed key if seed is provided
    key_pair = create_new_key_pair(generate_fixed_private_key(seed) if seed else None)
    logger.debug("[LISTENER] created key_pair=%s", type(key_pair).__name__)
    host = new_host(key_pair=key_pair)
    logger.debug("[LISTENER] host initialized | peer_id=%s", host.get_id())

    # Configure the circuit relay client (STOP role to accept connections)
    limits = RelayLimits(
        duration=3600,  # 1 hour
        data=1024 * 1024 * 100,  # 100 MB
        max_circuit_conns=10,
        max_reservations=5,
    )

    relay_config = RelayConfig(
        roles=RelayRole.STOP | RelayRole.CLIENT,  # Accept connections and use relays
        limits=limits,
    )

    # Initialize the protocol
    protocol = CircuitV2Protocol(host, limits=limits, allow_hop=False)
    logger.debug(
        "[LISTENER] CircuitV2Protocol initialized | allow_hop=%s",
        False,
    )

    # Initialize AutoNAT service
    # new_host() returns IHost but always returns BasicHost or RoutedHost
    autonat_service = AutoNATService(cast(BasicHost, host))
    logger.info("[LISTENER] AutoNAT service initialized")

    # Initialize DCUtR protocol
    dcutr_protocol = DCUtRProtocol(host)
    logger.info("[LISTENER] DCUtR protocol initialized")

    # Start the host
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run(listen_addrs=[listen_addr]):
        # Print information about this node
        peer_id = host.get_id()
        logger.info(f"Listener node started with ID: {peer_id}")

        addrs = host.get_addrs()
        for addr in addrs:
            logger.info(f"Listening on: {addr}")

        # Register protocol handlers
        logger.debug("[LISTENER] registering stream handlers")
        host.set_stream_handler(EXAMPLE_PROTOCOL_ID, handle_example_protocol)
        host.set_stream_handler(PROTOCOL_ID, protocol._handle_hop_stream)
        host.set_stream_handler(STOP_PROTOCOL_ID, protocol._handle_stop_stream)
        # Wrap bound method to match expected function signature
        # Streams are always NetStream instances in practice
        host.set_stream_handler(
            AUTONAT_PROTOCOL_ID,
            lambda stream: autonat_service.handle_stream(cast(NetStream, stream)),
        )
        logger.debug("[LISTENER] protocol handlers registered")

        # Start the relay protocol service
        async with background_trio_service(protocol):
            logger.info("Circuit relay protocol started")

            # Create and initialize transport
            transport = CircuitV2Transport(host, protocol, relay_config)
            logger.info(
                "Circuit relay transport initialized | "
                "enable_hop=%r enable_stop=%r enable_client=%r",
                relay_config.enable_hop,
                relay_config.enable_stop,
                relay_config.enable_client,
            )

            # Create discovery service
            discovery = RelayDiscovery(host, auto_reserve=True)
            transport.discovery = discovery
            logger.info(
                "[LISTENER] Relay discovery service created | auto_reserve=%s",
                True,
            )

            # Start discovery service
            async with background_trio_service(discovery):
                logger.info("Relay discovery service started")

                # Start DCUtR protocol service
                async with background_trio_service(dcutr_protocol):
                    logger.info("DCUtR protocol service started")

                    # Connect to the relay
                    if relay_addr:
                        logger.info(f"Connecting to relay at {relay_addr}")
                        try:
                            # Handle both peer ID only or full multiaddr formats
                            if relay_addr.startswith("/"):
                                # Full multiaddr format
                                relay_maddr = multiaddr.Multiaddr(relay_addr)
                                relay_info = info_from_p2p_addr(relay_maddr)
                            else:
                                # Assume it's just a peer ID
                                relay_peer_id = ID.from_string(relay_addr)
                                relay_info = PeerInfo(
                                    relay_peer_id,
                                    [
                                        multiaddr.Multiaddr(
                                            f"/ip4/127.0.0.1/tcp/8000/p2p/{relay_addr}"
                                        )
                                    ],
                                )
                                logger.info(
                                    f"Using constructed address: {relay_info.addrs[0]}"
                                )

                            logger.debug(
                                "[LISTENER] attempting host.connect to relay %s",
                                relay_info.peer_id,
                            )
                            await host.connect(relay_info)
                            logger.info(f"Connected to relay {relay_info.peer_id}")

                            # Wait a bit for relay discovery to complete
                            await trio.sleep(2)

                            # Update AutoNAT status periodically
                            async with trio.open_nursery() as nursery:
                                nursery.start_soon(log_autonat_status, autonat_service)

                                print("\n" + "=" * 60)
                                print("Listener node is running!")
                                print("=" * 60)
                                print(f"Peer ID: {peer_id}")
                                print(f"Listening on: {addrs[0] if addrs else 'N/A'}")
                                print(f"Connected to relay: {relay_info.peer_id}")
                                print("\nThis node is configured to:")
                                print("  - Accept connections via relay")
                                print(
                                    "  - Support DCUtR hole punching "
                                    "for direct connections"
                                )
                                print("  - Report AutoNAT reachability status")
                                print("\nPress Ctrl+C to exit\n")

                                # Keep the node running
                                await trio.sleep_forever()
                        except Exception as e:
                            logger.exception(
                                "[LISTENER] Failed to connect to relay: %s",
                                e,
                            )
                            return
                    else:
                        logger.error("Relay address is required")
                        return


def main() -> None:
    """Parse arguments and run the listener node."""
    parser = argparse.ArgumentParser(description="NAT Traversal Listener Node")
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port to listen on (default: 8001)",
    )
    parser.add_argument(
        "--relay-addr",
        type=str,
        required=True,
        help=(
            "Multiaddress or peer ID of relay node "
            "(e.g., /ip4/127.0.0.1/tcp/8000/p2p/PEER_ID)"
        ),
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
        trio.run(setup_listener_node, args.port, args.relay_addr, args.seed)
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
