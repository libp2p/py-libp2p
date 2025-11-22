#!/usr/bin/env python3
"""
Comprehensive example demonstrating all connection management features.

This example shows a production-ready configuration combining:
1. Connection limits
2. Rate limiting
3. Allow/deny lists
4. Connection state monitoring
5. Best practices
"""

import logging

import trio

from libp2p import new_swarm
from libp2p.network.config import ConnectionConfig

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_production_configuration() -> None:
    """Example of production-ready connection management configuration."""
    logger.info("=" * 60)
    logger.info("Example: Production Configuration")
    logger.info("=" * 60)

    # Production-ready configuration
    connection_config = ConnectionConfig(
        # Connection limits
        max_connections=300,
        max_connections_per_peer=3,
        max_parallel_dials=100,
        max_dial_queue_length=500,
        max_incoming_pending_connections=10,
        # Rate limiting
        inbound_connection_threshold=5,  # 5 connections/sec per host
        # Security - allow/deny lists
        allow_list=[
            "10.0.0.0/8",  # Internal network
            "192.168.0.0/16",  # Local network
        ],
        deny_list=[
            # Add known malicious IPs here
        ],
        # Timeouts
        dial_timeout=10.0,
        connection_close_timeout=1.0,
        inbound_upgrade_timeout=10.0,
        # Reconnection
        reconnect_retries=5,
        reconnect_retry_interval=1.0,
        reconnect_backoff_factor=2.0,
        max_parallel_reconnects=5,
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Production configuration applied:")
    logger.info(f"  Max connections: {connection_config.max_connections}")
    logger.info(f"  Max per peer: {connection_config.max_connections_per_peer}")
    logger.info(f"  Rate limit: {connection_config.inbound_connection_threshold}/sec")
    logger.info(f"  Allow list: {len(connection_config.allow_list)} entries")
    logger.info(f"  Deny list: {len(connection_config.deny_list)} entries")

    # Monitor connections
    connections = swarm.get_connections()
    logger.info(f"\nCurrent connections: {len(connections)}")

    await swarm.close()
    logger.info("Production configuration example completed\n")


async def example_high_performance_config() -> None:
    """Example of high-performance configuration."""
    logger.info("=" * 60)
    logger.info("Example: High-Performance Configuration")
    logger.info("=" * 60)

    # High-performance configuration
    connection_config = ConnectionConfig(
        max_connections=1000,
        max_connections_per_peer=5,
        max_parallel_dials=200,
        max_dial_queue_length=1000,
        inbound_connection_threshold=20,  # Higher threshold
        max_incoming_pending_connections=50,
        dial_timeout=5.0,  # Faster timeout
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("High-performance configuration:")
    logger.info(f"  Max connections: {connection_config.max_connections}")
    logger.info(f"  Max parallel dials: {connection_config.max_parallel_dials}")
    logger.info(f"  Rate limit: {connection_config.inbound_connection_threshold}/sec")
    logger.info("  Optimized for high throughput")

    await swarm.close()
    logger.info("High-performance configuration example completed\n")


async def example_restrictive_config() -> None:
    """Example of restrictive/secure configuration."""
    logger.info("=" * 60)
    logger.info("Example: Restrictive Configuration")
    logger.info("=" * 60)

    # Restrictive configuration
    connection_config = ConnectionConfig(
        max_connections=50,
        max_connections_per_peer=1,
        max_parallel_dials=10,
        inbound_connection_threshold=2,  # Lower threshold
        allow_list=["10.0.0.0/8"],  # Only allow internal network
        deny_list=[],  # Add known bad IPs
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Restrictive configuration:")
    logger.info(f"  Max connections: {connection_config.max_connections}")
    logger.info(f"  Rate limit: {connection_config.inbound_connection_threshold}/sec")
    logger.info("  Only allows connections from allow list")
    logger.info("  Suitable for secure/private networks")

    await swarm.close()
    logger.info("Restrictive configuration example completed\n")


async def example_monitoring_setup() -> None:
    """Example of setting up connection monitoring."""
    logger.info("=" * 60)
    logger.info("Example: Connection Monitoring")
    logger.info("=" * 60)

    connection_config = ConnectionConfig(max_connections=100)
    swarm = new_swarm(connection_config=connection_config)

    logger.info("Connection monitoring setup:")
    logger.info("  1. Track connection counts")
    logger.info("  2. Monitor rate limit violations")
    logger.info("  3. Log connection state changes")
    logger.info("  4. Alert on unusual patterns")

    # Get connection statistics
    connections = swarm.get_connections()
    logger.info("\nCurrent statistics:")
    logger.info(f"  Total connections: {len(connections)}")
    logger.info(f"  Max allowed: {connection_config.max_connections}")
    utilization = len(connections) / connection_config.max_connections * 100
    logger.info(f"  Utilization: {utilization:.1f}%")

    # Connection map
    if hasattr(swarm, "get_connections_map"):
        connections_map = swarm.get_connections_map()
        logger.info(f"  Unique peers: {len(connections_map)}")

    await swarm.close()
    logger.info("Connection monitoring example completed\n")


async def example_best_practices() -> None:
    """Example demonstrating best practices."""
    logger.info("=" * 60)
    logger.info("Example: Best Practices")
    logger.info("=" * 60)

    logger.info("Connection management best practices:")
    logger.info("\n1. Connection Limits:")
    logger.info("   - Set max_connections based on system resources")
    logger.info("   - Use max_connections_per_peer to prevent abuse")
    logger.info("   - Monitor connection counts regularly")

    logger.info("\n2. Rate Limiting:")
    logger.info("   - Configure based on expected traffic")
    logger.info("   - Balance between security and usability")
    logger.info("   - Monitor rate limit violations")

    logger.info("\n3. Allow/Deny Lists:")
    logger.info("   - Keep allow lists small and specific")
    logger.info("   - Regularly update deny lists")
    logger.info("   - Use CIDR blocks for network ranges")

    logger.info("\n4. Monitoring:")
    logger.info("   - Track connection state transitions")
    logger.info("   - Monitor connection lifecycle")
    logger.info("   - Alert on anomalies")

    logger.info("\n5. Configuration:")
    logger.info("   - Start with defaults and tune based on needs")
    logger.info("   - Test configurations in staging")
    logger.info("   - Document configuration decisions")


async def main() -> None:
    """Run comprehensive connection management examples."""
    logger.info("\n" + "=" * 60)
    logger.info("Comprehensive Connection Management Examples")
    logger.info("=" * 60 + "\n")

    try:
        await example_production_configuration()
        await example_high_performance_config()
        await example_restrictive_config()
        await example_monitoring_setup()
        await example_best_practices()

        logger.info("=" * 60)
        logger.info("All comprehensive examples completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Example failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    trio.run(main)
