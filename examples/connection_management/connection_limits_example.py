#!/usr/bin/env python3
"""
Example demonstrating connection limits and pruning.

This example shows how to:
1. Configure connection limits
2. Observe automatic connection pruning
3. Monitor connection counts
4. Handle connection limit exceeded scenarios
"""

import logging
from typing import TYPE_CHECKING

import trio

from libp2p import new_swarm
from libp2p.network.config import ConnectionConfig

if TYPE_CHECKING:
    pass

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_basic_connection_limits() -> None:
    """Example of basic connection limits configuration."""
    logger.info("=" * 60)
    logger.info("Example: Basic Connection Limits")
    logger.info("=" * 60)

    # Create swarm with low connection limit for demonstration
    connection_config = ConnectionConfig(
        max_connections=5,  # Very low limit for demo
        max_connections_per_peer=2,
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info(f"Swarm created with peer ID: {swarm.get_peer_id()}")
    logger.info(f"Max connections: {connection_config.max_connections}")
    max_per_peer = connection_config.max_connections_per_peer
    logger.info(f"Max connections per peer: {max_per_peer}")

    # Get current connection count
    connections = swarm.get_connections()
    logger.info(f"Current connections: {len(connections)}")

    await swarm.close()
    logger.info("Basic connection limits example completed\n")


async def example_connection_pruning() -> None:
    """Example demonstrating connection pruning behavior."""
    logger.info("=" * 60)
    logger.info("Example: Connection Pruning")
    logger.info("=" * 60)

    # Create swarm with connection limits
    connection_config = ConnectionConfig(
        max_connections=3,  # Low limit to trigger pruning
        max_connections_per_peer=1,
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Connection pruning behavior:")
    logger.info("  - When max_connections is exceeded, connections are pruned")
    logger.info("  - Pruning priority: peer tag value → stream count → direction → age")
    logger.info("  - Connections in allow list are never pruned")
    logger.info(f"  - Current max_connections: {connection_config.max_connections}")

    # Access connection pruner
    if hasattr(swarm, "connection_pruner"):
        logger.info("  - Connection pruner is active")

    await swarm.close()
    logger.info("Connection pruning example completed\n")


async def example_dynamic_limit_adjustment() -> None:
    """Example of dynamically adjusting connection limits."""
    logger.info("=" * 60)
    logger.info("Example: Dynamic Limit Adjustment")
    logger.info("=" * 60)

    connection_config = ConnectionConfig(max_connections=10)
    swarm = new_swarm(connection_config=connection_config)

    logger.info(f"Initial max_connections: {connection_config.max_connections}")

    # Simulate dynamic adjustment
    connection_config.max_connections = 5
    logger.info(f"Adjusted max_connections: {connection_config.max_connections}")
    logger.info("  - Reducing max_connections will trigger pruning if needed")

    # Increase limit
    connection_config.max_connections = 20
    logger.info(f"Increased max_connections: {connection_config.max_connections}")
    logger.info("  - Increasing max_connections allows more connections")

    await swarm.close()
    logger.info("Dynamic limit adjustment example completed\n")


async def example_per_peer_limits() -> None:
    """Example of per-peer connection limits."""
    logger.info("=" * 60)
    logger.info("Example: Per-Peer Connection Limits")
    logger.info("=" * 60)

    connection_config = ConnectionConfig(
        max_connections=100,  # Total connections
        max_connections_per_peer=3,  # Per-peer limit
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Per-peer connection limits:")
    logger.info(f"  - Max total connections: {connection_config.max_connections}")
    logger.info(f"  - Max per peer: {connection_config.max_connections_per_peer}")
    logger.info("  - This prevents a single peer from consuming all connections")

    await swarm.close()
    logger.info("Per-peer limits example completed\n")


async def example_connection_limit_exceeded() -> None:
    """Example of handling connection limit exceeded scenarios."""
    logger.info("=" * 60)
    logger.info("Example: Connection Limit Exceeded Handling")
    logger.info("=" * 60)

    connection_config = ConnectionConfig(
        max_connections=2,  # Very low limit
        max_incoming_pending_connections=1,
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("When connection limits are exceeded:")
    logger.info("  - New incoming connections are rejected")
    logger.info("  - Dial attempts may be queued or rejected")
    logger.info("  - Existing connections may be pruned to make room")
    logger.info(f"  - Current limit: {connection_config.max_connections}")

    await swarm.close()
    logger.info("Connection limit exceeded example completed\n")


async def main() -> None:
    """Run all connection limits examples."""
    logger.info("\n" + "=" * 60)
    logger.info("Connection Limits Examples")
    logger.info("=" * 60 + "\n")

    try:
        await example_basic_connection_limits()
        await example_connection_pruning()
        await example_dynamic_limit_adjustment()
        await example_per_peer_limits()
        await example_connection_limit_exceeded()

        logger.info("=" * 60)
        logger.info("All connection limits examples completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Example failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    trio.run(main)
