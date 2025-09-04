#!/usr/bin/env python3
"""
Example demonstrating connection health monitoring in libp2p.

This example shows how to:
1. Enable connection health monitoring
2. Configure health monitoring parameters
3. Use health-based load balancing strategies
4. Monitor connection health metrics
"""

import logging

import trio

from libp2p import new_swarm
from libp2p.network.swarm import ConnectionConfig

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_health_monitoring_basic() -> None:
    """Example of basic health monitoring setup."""
    logger.info("Creating swarm with health monitoring enabled...")

    # Create connection config with health monitoring
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,  # Check every 30 seconds
        ping_timeout=3.0,  # 3 second ping timeout
        min_health_threshold=0.4,  # Minimum health score
        min_connections_per_peer=2,  # Maintain at least 2 connections
        load_balancing_strategy="health_based"  # Use health-based selection
    )

    # Create swarm with health monitoring
    swarm = new_swarm(connection_config=connection_config)

    logger.info("Health monitoring configuration:")
    logger.info(f"  Enabled: {connection_config.enable_health_monitoring}")
    logger.info(f"  Check interval: {connection_config.health_check_interval}s")
    logger.info(f"  Ping timeout: {connection_config.ping_timeout}s")
    logger.info(f"  Min health threshold: {connection_config.min_health_threshold}")
    logger.info(
        f"  Min connections per peer: {connection_config.min_connections_per_peer}"
    )
    logger.info(f"  Load balancing: {connection_config.load_balancing_strategy}")

    await swarm.close()
    logger.info("Basic health monitoring example completed")


async def example_health_based_load_balancing() -> None:
    """Example of health-based load balancing strategies."""
    logger.info("Demonstrating health-based load balancing...")

    # Different load balancing strategies
    strategies = ["round_robin", "least_loaded", "health_based", "latency_based"]

    for strategy in strategies:
        connection_config = ConnectionConfig(
            enable_health_monitoring=True,
            load_balancing_strategy=strategy,
            health_check_interval=60.0
        )

        swarm = new_swarm(connection_config=connection_config)

        logger.info(f"Strategy '{strategy}':")
        logger.info(
            f"  Load balancing: {connection_config.load_balancing_strategy}"
        )
        logger.info(
            f"  Health monitoring: {connection_config.enable_health_monitoring}"
        )

        await swarm.close()

    logger.info("Health-based load balancing example completed")


async def example_health_monitoring_custom() -> None:
    """Example of custom health monitoring configuration."""
    logger.info("Creating custom health monitoring configuration...")

    # Custom configuration for production use
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        max_connections_per_peer=5,  # More connections for redundancy
        health_check_interval=120.0,  # Less frequent checks in production
        ping_timeout=10.0,  # Longer timeout for slow networks
        min_health_threshold=0.6,  # Higher threshold for production
        min_connections_per_peer=3,  # Maintain more connections
        load_balancing_strategy="health_based"  # Prioritize healthy connections
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Custom health monitoring configuration:")
    logger.info(
        f"  Max connections per peer: {connection_config.max_connections_per_peer}"
    )
    logger.info(f"  Health check interval: {connection_config.health_check_interval}s")
    logger.info(f"  Ping timeout: {connection_config.ping_timeout}s")
    logger.info(f"  Min health threshold: {connection_config.min_health_threshold}")
    logger.info(
        f"  Min connections per peer: {connection_config.min_connections_per_peer}"
    )

    await swarm.close()
    logger.info("Custom health monitoring example completed")


async def example_health_monitoring_disabled() -> None:
    """Example of disabling health monitoring."""
    logger.info("Creating swarm with health monitoring disabled...")

    # Disable health monitoring for performance-critical scenarios
    connection_config = ConnectionConfig(
        enable_health_monitoring=False,
        load_balancing_strategy="round_robin"  # Fall back to simple strategy
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Health monitoring disabled configuration:")
    logger.info(f"  Enabled: {connection_config.enable_health_monitoring}")
    logger.info(f"  Load balancing: {connection_config.load_balancing_strategy}")
    logger.info("  Note: Health-based strategies will fall back to round-robin")

    await swarm.close()
    logger.info("Health monitoring disabled example completed")


async def main() -> None:
    """Run all health monitoring examples."""
    logger.info("=== Connection Health Monitoring Examples ===\n")

    await example_health_monitoring_basic()
    logger.info("")

    await example_health_based_load_balancing()
    logger.info("")

    await example_health_monitoring_custom()
    logger.info("")

    await example_health_monitoring_disabled()

    logger.info("\n=== All examples completed ===")


if __name__ == "__main__":
    trio.run(main)
