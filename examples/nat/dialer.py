"""
NAT Traversal Dialer Node Example.

This module implements a NAT'd peer that:
- Connects to a destination through a Circuit Relay v2 relay
- Attempts DCUtR (Direct Connection Upgrade through Relay) hole punching
- Uses AutoNAT to detect and report reachability status
- Logs the connection path (direct or relayed)

Usage:
    python dialer.py --relay-addr /ip4/127.0.0.1/tcp/8000/p2p/RELAY_PEER_ID \
        --listener-id LISTENER_PEER_ID
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
from libp2p.host.basic_host import BasicHost
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.dcutr import DCUtRProtocol
from libp2p.relay.circuit_v2.discovery import RelayDiscovery
from libp2p.relay.circuit_v2.protocol import (
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
logger = logging.getLogger("nat-dialer")

# Application protocol for testing
EXAMPLE_PROTOCOL_ID = TProtocol("/nat-example/1.0.0")
MAX_READ_LEN = 2**16  # 64KB


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


def is_connection_direct(host, peer_id: ID) -> bool:
    """Check if we have a direct connection to a peer."""
    try:
        network = host.get_network()
        conn_or_conns = network.connections.get(peer_id)
        if not conn_or_conns:
            return False

        # Handle both single connection and list of connections
        if isinstance(conn_or_conns, list):
            connections = conn_or_conns
        else:
            connections = [conn_or_conns]

        # Check if any connection is direct (not relayed)
        for conn in connections:
            try:
                addrs = conn.get_transport_addresses()
                if addrs and any(
                    not str(addr).startswith("/p2p-circuit") for addr in addrs
                ):
                    return True
            except Exception:
                # If we can't get addresses, try checking the raw connection
                try:
                    if hasattr(conn, "muxed_conn") and hasattr(
                        conn.muxed_conn, "raw_conn"
                    ):
                        raw_conn = conn.muxed_conn.raw_conn
                        raw_addrs = raw_conn.get_transport_addresses()
                        if raw_addrs and any(
                            not str(addr).startswith("/p2p-circuit")
                            for addr in raw_addrs
                        ):
                            return True
                except Exception:
                    pass
                # If we can't verify, assume it's relayed
                continue

        return False
    except Exception:
        return False


async def setup_dialer_node(
    relay_addr: str, listener_id: str, seed: int | None = None
) -> None:
    """
    Set up and run a dialer node that connects through relay and attempts hole punching.
    """
    logger.info("Starting dialer node (behind NAT)...")

    if not relay_addr:
        logger.error("Relay address is required")
        return

    if not listener_id:
        logger.error("Listener peer ID is required")
        return

    # Create host with a fixed key if seed is provided
    key_pair = create_new_key_pair(generate_fixed_private_key(seed) if seed else None)
    logger.debug("[DIALER] created key_pair=%s", type(key_pair).__name__)
    host = new_host(key_pair=key_pair)
    logger.debug("[DIALER] host initialized | peer_id=%s", host.get_id())

    # Configure the circuit relay client
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
        "[DIALER] CircuitV2Protocol initialized | allow_hop=%s",
        False,
    )

    # Initialize AutoNAT service
    # new_host() returns IHost but always returns BasicHost or RoutedHost
    autonat_service = AutoNATService(cast(BasicHost, host))
    logger.info("[DIALER] AutoNAT service initialized")

    # Initialize DCUtR protocol
    dcutr_protocol = DCUtRProtocol(host)
    logger.info("[DIALER] DCUtR protocol initialized")

    # Start the host
    async with host.run(
        listen_addrs=[multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")]
    ):  # Use ephemeral port
        # Print information about this node
        peer_id = host.get_id()
        logger.info(f"Dialer node started with ID: {peer_id}")

        # Get assigned address for debugging
        addrs = host.get_addrs()
        if addrs:
            logger.info(f"Dialer node listening on: {addrs[0]}")

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
                "[DIALER] Relay discovery service created | auto_reserve=%s",
                True,
            )

            # Start discovery service
            async with background_trio_service(discovery):
                logger.info("Relay discovery service started")

                # Start DCUtR protocol service
                async with background_trio_service(dcutr_protocol):
                    logger.info("DCUtR protocol service started")

                    # Connect to the relay
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
                            "[DIALER] attempting host.connect to relay %s",
                            relay_info.peer_id,
                        )
                        await host.connect(relay_info)
                        logger.info(f"Connected to relay {relay_info.peer_id}")

                        # Wait for relay discovery to find the relay
                        await trio.sleep(2)
                        try:
                            relays = transport.discovery.get_relays()
                            logger.debug("[DIALER] discovered relays: %s", relays)
                        except Exception:
                            pass

                        # Convert listener ID string to peer ID
                        listener_peer_id = ID.from_string(listener_id)

                        # Step 1: Connect to listener through relay
                        logger.info(
                            f"Step 1: Connecting to listener {listener_peer_id} "
                            f"through relay"
                        )

                        # Create a proper circuit address
                        # Format: /ip4/.../tcp/.../p2p/RELAY_PEER_ID/
                        #         p2p-circuit/p2p/DEST_PEER_ID
                        # First, get a proper relay address
                        # (replace 0.0.0.0 with 127.0.0.1 for localhost)
                        relay_addr_str = str(relay_info.addrs[0])
                        if "0.0.0.0" in relay_addr_str:
                            relay_addr_str = relay_addr_str.replace(
                                "0.0.0.0", "127.0.0.1"
                            )

                        # Ensure the relay peer ID is in the address before p2p-circuit
                        relay_peer_id_str = str(relay_info.peer_id)
                        if f"/p2p/{relay_peer_id_str}" not in relay_addr_str:
                            # Add the relay peer ID if not present
                            relay_addr_str = f"{relay_addr_str}/p2p/{relay_peer_id_str}"

                        # Construct the circuit address
                        circuit_addr = multiaddr.Multiaddr(
                            f"{relay_addr_str}/p2p-circuit/p2p/{listener_peer_id}"
                        )
                        logger.info(f"Using circuit address: {circuit_addr}")

                        # Dial through the relay
                        try:
                            logger.info(
                                f"Attempting to dial listener {listener_peer_id} "
                                f"through relay {relay_info.peer_id}"
                            )

                            logger.debug(
                                "[DIALER] dialing via transport: dest=%s relay=%s",
                                listener_peer_id,
                                relay_info.peer_id,
                            )
                            connection = await transport.dial(circuit_addr)
                            logger.info("Established relay connection: %s", connection)

                            logger.info(
                                "✓ Successfully connected to listener through relay!"
                            )

                            # Wait a bit for the connection to stabilize
                            await trio.sleep(1)

                            # Step 2: Attempt DCUtR hole punching
                            logger.info(
                                "Step 2: Attempting DCUtR hole punching "
                                "for direct connection..."
                            )

                            # Wait for DCUtR protocol to be ready
                            await dcutr_protocol.event_started.wait()

                            # Attempt hole punch
                            hole_punch_success = (
                                await dcutr_protocol.initiate_hole_punch(
                                    listener_peer_id
                                )
                            )

                            if hole_punch_success:
                                logger.info(
                                    "✓ Successfully established direct "
                                    "connection via DCUtR!"
                                )
                            else:
                                logger.info(
                                    "⚠ Hole punching failed or not possible, "
                                    "continuing with relay connection"
                                )

                            # Wait a bit more
                            await trio.sleep(2)

                            # Check final connection type using DCUtR's verification
                            # This is more reliable than our simple check
                            is_direct = await dcutr_protocol._verify_direct_connection(
                                listener_peer_id
                            )
                            if not is_direct:
                                # Fallback to our check
                                is_direct = is_connection_direct(host, listener_peer_id)
                            connection_type = "DIRECT" if is_direct else "RELAYED"
                            logger.info(
                                f"Final connection type to listener: {connection_type}"
                            )

                            # Also check what the stream actually uses
                            # We'll verify this when we open the stream

                            # Step 3: Open a stream and send a message
                            logger.info(
                                "Step 3: Opening stream to listener "
                                "and sending message..."
                            )
                            logger.debug(
                                "[DIALER] opening app stream to %s with %s",
                                listener_peer_id,
                                EXAMPLE_PROTOCOL_ID,
                            )
                            stream = await host.new_stream(
                                listener_peer_id, [EXAMPLE_PROTOCOL_ID]
                            )
                            if stream:
                                # Verify the actual stream connection type
                                actual_connection_type = "RELAYED"  # Default
                                try:
                                    # raw_conn is implementation-specific,
                                    # not in IMuxedConn interface
                                    conn = (
                                        stream.muxed_conn.raw_conn  # type: ignore[attr-defined]
                                    )
                                    addrs = conn.get_transport_addresses()
                                    if addrs:
                                        # Check if any address indicates circuit
                                        if any(
                                            "/p2p-circuit" in str(addr)
                                            for addr in addrs
                                        ):
                                            actual_connection_type = "RELAYED"
                                        elif any(
                                            "127.0.0.1" in str(addr)
                                            and "8000" in str(addr)
                                            for addr in addrs
                                        ):
                                            # If connecting to relay port,
                                            # it's likely relayed
                                            actual_connection_type = "RELAYED"
                                        else:
                                            actual_connection_type = "DIRECT"
                                except Exception:
                                    pass

                                logger.info(
                                    f"✓ Opened stream to listener with protocol "
                                    f"{EXAMPLE_PROTOCOL_ID} "
                                    f"(detected: {actual_connection_type}, "
                                    f"reported: {connection_type})"
                                )

                                # Update connection type based on actual stream
                                if actual_connection_type != connection_type:
                                    logger.warning(
                                        f"Connection type mismatch: "
                                        f"reported {connection_type} "
                                        f"but stream indicates "
                                        f"{actual_connection_type}"
                                    )
                                    connection_type = actual_connection_type

                                # Send a message
                                msg = f"Hello from dialer {peer_id}!".encode()
                                logger.debug(
                                    "[DIALER] writing %d bytes on app stream", len(msg)
                                )
                                await stream.write(msg)
                                logger.info("Sent message to listener")

                                # Wait for response
                                logger.debug(
                                    "[DIALER] waiting to read up to %d bytes "
                                    "on app stream",
                                    MAX_READ_LEN,
                                )
                                response = await stream.read(MAX_READ_LEN)
                                response_str = (
                                    response.decode() if response else "No response"
                                )
                                logger.info(f"✓ Received response: {response_str}")

                                # Close the stream
                                await stream.close()
                            else:
                                logger.error("Failed to open stream to listener")

                            # Log AutoNAT status
                            autonat_status = autonat_service.get_status()
                            status_str = get_autonat_status_string(autonat_status)
                            logger.info(f"[AutoNAT] Reachability status: {status_str}")

                            print("\n" + "=" * 60)
                            print("Connection Summary")
                            print("=" * 60)
                            print(f"Dialer Peer ID: {peer_id}")
                            print(f"Listener Peer ID: {listener_peer_id}")
                            print(f"Connection Type: {connection_type}")
                            print(f"AutoNAT Status: {status_str}")
                            print("=" * 60)

                            # Keep running for a bit to allow messages to be processed
                            await trio.sleep(5)

                        except Exception as e:
                            logger.exception(
                                "[DIALER] Failed to dial through relay: %s", e
                            )
                            logger.error(f"Exception type: {type(e).__name__}")
                            raise

                    except Exception as e:
                        logger.exception("[DIALER] Error: %s", e)

                    print("\nDialer operation completed")
                    # Keep running for a bit to allow messages to be processed
                    await trio.sleep(5)


def main() -> None:
    """Parse arguments and run the dialer node."""
    parser = argparse.ArgumentParser(description="NAT Traversal Dialer Node")
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
        "--listener-id",
        type=str,
        required=True,
        help="Peer ID of listener node",
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
        trio.run(setup_dialer_node, args.relay_addr, args.listener_id, args.seed)
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
