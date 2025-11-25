#!/usr/bin/env python3
"""
Example demonstrating connection state management.

This example shows how to:
1. Monitor connection states
2. Track connection lifecycle
3. Handle state transitions
4. Query connection information
"""

import logging
import secrets
from typing import cast

import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.utils.address_validation import get_available_interfaces

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_connection_states() -> None:
    """Example of connection state tracking."""
    logger.info("=" * 60)
    logger.info("Example: Connection States")
    logger.info("=" * 60)

    logger.info("Connection state lifecycle:")
    logger.info("  1. PENDING - Connection is being established")
    logger.info("  2. OPEN - Connection is active and ready")
    logger.info("  3. CLOSING - Connection is being closed")
    logger.info("  4. CLOSED - Connection is fully closed")

    # Create two hosts
    key_pair_1 = create_new_key_pair(secrets.token_bytes(32))
    key_pair_2 = create_new_key_pair(secrets.token_bytes(32))

    host_1 = new_host(key_pair=key_pair_1)
    host_2 = new_host(key_pair=key_pair_2)

    listen_addrs_1 = get_available_interfaces(8000)
    listen_addrs_2 = get_available_interfaces(8001)

    async with (
        host_1.run(listen_addrs=listen_addrs_1),
        host_2.run(listen_addrs=listen_addrs_2),
    ):
        await trio.sleep(1)

        # Connect host_2 to host_1
        addr_1 = host_1.get_addrs()[0]
        peer_info = PeerInfo(host_1.get_id(), [addr_1])
        await host_2.connect(peer_info)

        # Wait a bit for connection to be fully established
        await trio.sleep(0.5)

        logger.info("\n✅ Connected host_2 to host_1")

        # Get connections from both sides
        swarm_1 = host_1.get_network()
        swarm_2 = host_2.get_network()

        connections_1 = swarm_1.get_connections()
        connections_2 = swarm_2.get_connections()

        logger.info(f"\nCurrent connections on host_1 (inbound): {len(connections_1)}")
        logger.info(f"Current connections on host_2 (outbound): {len(connections_2)}")

        # Show connections from host_1's perspective (inbound)
        for conn in connections_1:
            direction = getattr(conn, "direction", "unknown")
            peer_id: ID | str = (
                conn.muxed_conn.peer_id if hasattr(conn, "muxed_conn") else "unknown"
            )
            peer_id_str = (
                peer_id.pretty()[:20] if isinstance(peer_id, ID) else str(peer_id)
            )
            logger.info(
                f"  Host_1 → Connection from {peer_id_str}... - Direction: {direction}"
            )
            logger.info(f"    Is closed: {conn.is_closed}")
            logger.info(f"    Active streams: {len(conn.get_streams())}")

        # Show connections from host_2's perspective (outbound)
        for conn in connections_2:
            direction = getattr(conn, "direction", "unknown")
            peer_id: ID | str = (
                conn.muxed_conn.peer_id if hasattr(conn, "muxed_conn") else "unknown"
            )
            peer_id_str = (
                peer_id.pretty()[:20] if isinstance(peer_id, ID) else str(peer_id)
            )
            logger.info(
                f"  Host_2 → Connection to {peer_id_str}... - Direction: {direction}"
            )
            logger.info(f"    Is closed: {conn.is_closed}")
            logger.info(f"    Active streams: {len(conn.get_streams())}")

        await trio.sleep(0.5)

    logger.info("Connection states example completed\n")


async def example_connection_timeline() -> None:
    """Example of connection timeline tracking."""
    logger.info("=" * 60)
    logger.info("Example: Connection Timeline")
    logger.info("=" * 60)

    logger.info("Connection timeline tracks:")
    logger.info("  - Created at: Timestamp when connection was created")
    logger.info("  - Closed at: Timestamp when connection was closed (if applicable)")

    # Create two hosts
    key_pair_1 = create_new_key_pair(secrets.token_bytes(32))
    key_pair_2 = create_new_key_pair(secrets.token_bytes(32))

    host_1 = new_host(key_pair=key_pair_1)
    host_2 = new_host(key_pair=key_pair_2)

    listen_addrs_1 = get_available_interfaces(8002)
    listen_addrs_2 = get_available_interfaces(8003)

    async with (
        host_1.run(listen_addrs=listen_addrs_1),
        host_2.run(listen_addrs=listen_addrs_2),
    ):
        await trio.sleep(1)

        # Connect host_2 to host_1
        addr_1 = host_1.get_addrs()[0]
        peer_info = PeerInfo(host_1.get_id(), [addr_1])
        await host_2.connect(peer_info)

        # Wait a bit for connection to be fully established
        await trio.sleep(0.5)

        logger.info("\n✅ Connected host_2 to host_1")

        # Get connections and show timeline (check from host_2's perspective)
        swarm_2 = host_2.get_network()
        connections = swarm_2.get_connections()
        logger.info(f"\nTracking timeline for {len(connections)} connections")

        for conn in connections:
            peer_id: ID | str = (
                conn.muxed_conn.peer_id if hasattr(conn, "muxed_conn") else "unknown"
            )
            created_at = getattr(conn, "_created_at", None)
            if created_at:
                import time

                age = time.time() - created_at
                peer_id_str = (
                    peer_id.pretty()[:20] if isinstance(peer_id, ID) else str(peer_id)
                )
                logger.info(f"  Connection to {peer_id_str}...:")
                logger.info(f"    - Created at: {created_at:.2f}")
                logger.info(f"    - Age: {age:.2f} seconds")
                logger.info(f"    - Is closed: {conn.is_closed}")
                logger.info(f"    - Direction: {getattr(conn, 'direction', 'unknown')}")

        await trio.sleep(0.5)

    logger.info("Connection timeline example completed\n")


async def example_connection_queries() -> None:
    """Example of querying connection information."""
    logger.info("=" * 60)
    logger.info("Example: Connection Queries")
    logger.info("=" * 60)

    logger.info("Available connection queries:")
    logger.info("  - get_connections(): Get all connections")
    logger.info("  - get_connections(peer_id): Get connections for a peer")
    logger.info("  - get_connections_map(): Get map of peer -> connections")
    logger.info("  - get_total_connections(): Get total connection count")

    # Create multiple hosts
    key_pair_1 = create_new_key_pair(secrets.token_bytes(32))
    key_pair_2 = create_new_key_pair(secrets.token_bytes(32))
    key_pair_3 = create_new_key_pair(secrets.token_bytes(32))

    host_1 = new_host(key_pair=key_pair_1)
    host_2 = new_host(key_pair=key_pair_2)
    host_3 = new_host(key_pair=key_pair_3)

    listen_addrs_1 = get_available_interfaces(8004)
    listen_addrs_2 = get_available_interfaces(8005)
    listen_addrs_3 = get_available_interfaces(8006)

    async with (
        host_1.run(listen_addrs=listen_addrs_1),
        host_2.run(listen_addrs=listen_addrs_2),
        host_3.run(listen_addrs=listen_addrs_3),
    ):
        await trio.sleep(1)

        # Connect host_2 and host_3 to host_1
        addr_1 = host_1.get_addrs()[0]
        peer_info_1 = PeerInfo(host_1.get_id(), [addr_1])
        await host_2.connect(peer_info_1)
        await trio.sleep(0.3)
        await host_3.connect(peer_info_1)

        # Wait for connections to be established
        await trio.sleep(0.5)

        logger.info("\n✅ Connected host_2 and host_3 to host_1")

        # Get connections from host_1's network (inbound connections)
        swarm_1 = cast(Swarm, host_1.get_network())

        # Get all connections
        all_connections = swarm_1.get_connections()
        logger.info(f"\nTotal connections on host_1: {len(all_connections)}")

        # Get connections map
        connections_map = swarm_1.get_connections_map()
        logger.info(f"Peers with connections: {len(connections_map)}")

        for peer_id, conns in connections_map.items():
            logger.info(
                f"  Peer {peer_id.pretty()[:20]}...: {len(conns)} connection(s)"
            )
            for conn in conns:
                direction = getattr(conn, "direction", "unknown")
                logger.info(
                    f"    - Direction: {direction}, Streams: {len(conn.get_streams())}"
                )

        # Get total connections
        total = swarm_1.get_total_connections()
        logger.info(f"\nTotal connections (via get_total_connections()): {total}")

        await trio.sleep(0.5)

    logger.info("Connection queries example completed\n")


async def example_state_transitions() -> None:
    """Example of connection state transitions."""
    logger.info("=" * 60)
    logger.info("Example: State Transitions")
    logger.info("=" * 60)

    logger.info("Connection state transitions:")
    logger.info("  PENDING → OPEN (when connection established)")
    logger.info("  OPEN → CLOSING (when close() is called)")
    logger.info("  CLOSING → CLOSED (when close completes)")
    logger.info("  Any state → CLOSED (on error)")

    logger.info("\nState transition rules:")
    logger.info("  - States are managed internally")
    logger.info("  - Transitions are automatic")
    logger.info("  - Can monitor via connection events")

    # Create two hosts
    key_pair_1 = create_new_key_pair(secrets.token_bytes(32))
    key_pair_2 = create_new_key_pair(secrets.token_bytes(32))

    host_1 = new_host(key_pair=key_pair_1)
    host_2 = new_host(key_pair=key_pair_2)

    listen_addrs_1 = get_available_interfaces(8007)
    listen_addrs_2 = get_available_interfaces(8008)

    async with (
        host_1.run(listen_addrs=listen_addrs_1),
        host_2.run(listen_addrs=listen_addrs_2),
    ):
        await trio.sleep(1)

        # Connect host_2 to host_1
        addr_1 = host_1.get_addrs()[0]
        peer_info = PeerInfo(host_1.get_id(), [addr_1])
        await host_2.connect(peer_info)

        # Wait for connection to be established
        await trio.sleep(0.5)

        logger.info("\n✅ Connection established (OPEN state)")

        # Check from host_2's perspective (outbound connection)
        swarm_2 = host_2.get_network()
        connections = swarm_2.get_connections()

        if connections:
            conn = connections[0]
            logger.info(f"  Connection state before close: is_closed={conn.is_closed}")
            logger.info(f"  Direction: {getattr(conn, 'direction', 'unknown')}")

            # Close the connection
            await conn.close()
            await trio.sleep(0.2)

            logger.info(f"  Connection state after close: is_closed={conn.is_closed}")
            logger.info("  ✅ Demonstrated OPEN → CLOSED transition")
        else:
            logger.info("  No connections found to demonstrate state transition")

        await trio.sleep(0.5)

    logger.info("State transitions example completed\n")


async def example_connection_metadata() -> None:
    """Example of accessing connection metadata."""
    logger.info("=" * 60)
    logger.info("Example: Connection Metadata")
    logger.info("=" * 60)

    # Create two hosts
    key_pair_1 = create_new_key_pair(secrets.token_bytes(32))
    key_pair_2 = create_new_key_pair(secrets.token_bytes(32))

    host_1 = new_host(key_pair=key_pair_1)
    host_2 = new_host(key_pair=key_pair_2)

    listen_addrs_1 = get_available_interfaces(8009)
    listen_addrs_2 = get_available_interfaces(8010)

    async with (
        host_1.run(listen_addrs=listen_addrs_1),
        host_2.run(listen_addrs=listen_addrs_2),
    ):
        await trio.sleep(1)

        # Connect host_2 to host_1
        addr_1 = host_1.get_addrs()[0]
        peer_info = PeerInfo(host_1.get_id(), [addr_1])
        await host_2.connect(peer_info)

        # Wait for connection to be established
        await trio.sleep(0.5)

        logger.info("\n✅ Connected host_2 to host_1")

        # Check from host_2's perspective (outbound connection)
        swarm_2 = host_2.get_network()
        connections = swarm_2.get_connections()
        logger.info(f"\nAccessing metadata for {len(connections)} connections")

        for conn in connections:
            logger.info("\nConnection metadata:")

            # Peer ID
            if hasattr(conn, "muxed_conn") and hasattr(conn.muxed_conn, "peer_id"):
                peer_id = conn.muxed_conn.peer_id
                logger.info(f"  Peer ID: {peer_id.pretty()}")

            # Direction
            direction = getattr(conn, "direction", "unknown")
            logger.info(f"  Direction: {direction}")

            # Streams
            streams = conn.get_streams()
            logger.info(f"  Active streams: {len(streams)}")

            # Connection state
            is_closed = conn.is_closed
            logger.info(f"  Is closed: {is_closed}")

            # Created timestamp
            created_at = getattr(conn, "_created_at", None)
            if created_at:
                import time

                age = time.time() - created_at
                logger.info(f"  Created at: {created_at:.2f}")
                logger.info(f"  Age: {age:.2f} seconds")

            # Transport addresses
            try:
                transport_addrs = conn.get_transport_addresses()
                if transport_addrs:
                    logger.info(f"  Transport addresses: {len(transport_addrs)}")
                    for addr in transport_addrs[:2]:  # Show first 2
                        logger.info(f"    - {addr}")
            except Exception as e:
                logger.debug(f"  Could not get transport addresses: {e}")

        await trio.sleep(0.5)

    logger.info("Connection metadata example completed\n")


async def main() -> None:
    """Run all connection state examples."""
    logger.info("\n" + "=" * 60)
    logger.info("Connection State Management Examples")
    logger.info("=" * 60 + "\n")

    try:
        await example_connection_states()
        await example_connection_timeline()
        await example_connection_queries()
        await example_state_transitions()
        await example_connection_metadata()

        logger.info("=" * 60)
        logger.info("All connection state examples completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Example failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    trio.run(main)
