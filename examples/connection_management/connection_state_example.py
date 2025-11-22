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

import trio

from libp2p import new_swarm

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_connection_states() -> None:
    """Example of connection state tracking."""
    logger.info("=" * 60)
    logger.info("Example: Connection States")
    logger.info("=" * 60)

    swarm = new_swarm()

    logger.info("Connection state lifecycle:")
    logger.info("  1. PENDING - Connection is being established")
    logger.info("  2. OPEN - Connection is active and ready")
    logger.info("  3. CLOSING - Connection is being closed")
    logger.info("  4. CLOSED - Connection is fully closed")

    # Get current connections
    connections = swarm.get_connections()
    logger.info(f"\nCurrent connections: {len(connections)}")

    for conn in connections:
        # Access connection state if available
        state = getattr(conn, "state", None)
        if state is not None:
            logger.info(f"  Connection state: {state}")
        else:
            status = getattr(conn, "status", None)
            if status is not None:
                logger.info(f"  Connection status: {status}")

    await swarm.close()
    logger.info("Connection states example completed\n")


async def example_connection_timeline() -> None:
    """Example of connection timeline tracking."""
    logger.info("=" * 60)
    logger.info("Example: Connection Timeline")
    logger.info("=" * 60)

    swarm = new_swarm()

    logger.info("Connection timeline tracks:")
    logger.info("  - open: Timestamp when connection was opened")
    logger.info("  - close: Timestamp when connection was closed (if applicable)")

    connections = swarm.get_connections()
    logger.info(f"\nTracking timeline for {len(connections)} connections")

    # Access timeline if available
    for conn in connections:
        state = getattr(conn, "state", None)
        if state is not None:
            timeline = getattr(state, "timeline", None)
            if timeline is not None:
                logger.info("  Connection timeline:")
                open_time = getattr(timeline, "open", None)
                if open_time is not None:
                    logger.info(f"    - Open: {open_time}")
                close_time = getattr(timeline, "close", None)
                if close_time is not None:
                    logger.info(f"    - Close: {close_time}")

    await swarm.close()
    logger.info("Connection timeline example completed\n")


async def example_connection_queries() -> None:
    """Example of querying connection information."""
    logger.info("=" * 60)
    logger.info("Example: Connection Queries")
    logger.info("=" * 60)

    swarm = new_swarm()

    logger.info("Available connection queries:")
    logger.info("  - get_connections(): Get all connections")
    logger.info("  - get_connections(peer_id): Get connections for a peer")
    logger.info("  - get_connections_map(): Get map of peer -> connections")

    # Get all connections
    all_connections = swarm.get_connections()
    logger.info(f"\nTotal connections: {len(all_connections)}")

    # Get connections map
    if hasattr(swarm, "get_connections_map"):
        connections_map = swarm.get_connections_map()
        logger.info(f"Peers with connections: {len(connections_map)}")

        for peer_id, conns in connections_map.items():
            logger.info(f"  Peer {peer_id}: {len(conns)} connection(s)")

    await swarm.close()
    logger.info("Connection queries example completed\n")


async def example_state_transitions() -> None:
    """Example of connection state transitions."""
    logger.info("=" * 60)
    logger.info("Example: State Transitions")
    logger.info("=" * 60)

    swarm = new_swarm()

    logger.info("Connection state transitions:")
    logger.info("  PENDING → OPEN (when connection established)")
    logger.info("  OPEN → CLOSING (when close() is called)")
    logger.info("  CLOSING → CLOSED (when close completes)")
    logger.info("  Any state → CLOSED (on error)")

    logger.info("\nState transition rules:")
    logger.info("  - States are managed internally")
    logger.info("  - Transitions are automatic")
    logger.info("  - Can monitor via connection events")

    await swarm.close()
    logger.info("State transitions example completed\n")


async def example_connection_metadata() -> None:
    """Example of accessing connection metadata."""
    logger.info("=" * 60)
    logger.info("Example: Connection Metadata")
    logger.info("=" * 60)

    swarm = new_swarm()

    connections = swarm.get_connections()
    logger.info(f"Accessing metadata for {len(connections)} connections")

    for conn in connections:
        logger.info("\nConnection metadata:")

        # Peer ID
        if hasattr(conn, "muxed_conn") and hasattr(conn.muxed_conn, "peer_id"):
            logger.info(f"  Peer ID: {conn.muxed_conn.peer_id}")

        # Streams
        if hasattr(conn, "get_streams"):
            streams = conn.get_streams()
            logger.info(f"  Active streams: {len(streams) if streams else 0}")

        # State
        state = getattr(conn, "state", None)
        if state is not None:
            status = getattr(state, "status", None)
            if status is not None:
                state_str = status
            else:
                state_str = str(state)
            logger.info(f"  State: {state_str}")

    await swarm.close()
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
