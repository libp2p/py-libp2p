#!/usr/bin/env python3
"""
Example demonstrating connection rate limiting.

This example shows how to:
1. Configure rate limiting for incoming connections
2. Understand rate limiting behavior
3. Handle rate limit exceeded scenarios
"""

import logging

import trio

from libp2p import new_swarm
from libp2p.network.config import ConnectionConfig

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_basic_rate_limiting() -> None:
    """Example of basic rate limiting configuration."""
    logger.info("=" * 60)
    logger.info("Example: Basic Rate Limiting")
    logger.info("=" * 60)

    # Configure rate limiting
    connection_config = ConnectionConfig(
        inbound_connection_threshold=5,  # 5 connections per second per host
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Rate limiting configuration:")
    threshold = connection_config.inbound_connection_threshold
    logger.info(f"  - Inbound connection threshold: {threshold} connections/sec")
    logger.info("  - Rate limiting is per-host (IP address)")
    logger.info("  - Prevents connection flooding attacks")

    await swarm.close()
    logger.info("Basic rate limiting example completed\n")


async def example_rate_limit_behavior() -> None:
    """Example demonstrating rate limit behavior."""
    logger.info("=" * 60)
    logger.info("Example: Rate Limit Behavior")
    logger.info("=" * 60)

    connection_config = ConnectionConfig(
        inbound_connection_threshold=3,  # Low threshold for demo
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Rate limiting behavior:")
    logger.info("  - Tracks connection attempts per IP address")
    logger.info("  - Resets after the time window (1 second)")
    logger.info("  - Connections exceeding threshold are rejected")
    threshold = connection_config.inbound_connection_threshold
    logger.info(f"  - Current threshold: {threshold}/sec")

    # Access rate limiter if available
    if hasattr(swarm, "connection_gate"):
        logger.info("  - Rate limiter is active via connection gate")

    await swarm.close()
    logger.info("Rate limit behavior example completed\n")


async def example_custom_rate_limits() -> None:
    """Example of custom rate limit configuration."""
    logger.info("=" * 60)
    logger.info("Example: Custom Rate Limits")
    logger.info("=" * 60)

    # High-traffic scenario
    high_traffic_config = ConnectionConfig(
        inbound_connection_threshold=20,  # Higher threshold
        max_incoming_pending_connections=50,
    )

    logger.info("High-traffic configuration:")
    threshold = high_traffic_config.inbound_connection_threshold
    logger.info(f"  - Threshold: {threshold}/sec")
    max_pending = high_traffic_config.max_incoming_pending_connections
    logger.info(f"  - Max pending: {max_pending}")

    # Low-traffic scenario
    low_traffic_config = ConnectionConfig(
        inbound_connection_threshold=2,  # Lower threshold
        max_incoming_pending_connections=5,
    )

    logger.info("\nLow-traffic configuration:")
    threshold = low_traffic_config.inbound_connection_threshold
    logger.info(f"  - Threshold: {threshold}/sec")
    max_pending = low_traffic_config.max_incoming_pending_connections
    logger.info(f"  - Max pending: {max_pending}")

    logger.info("\nRate limits should be configured based on:")
    logger.info("  - Expected traffic patterns")
    logger.info("  - Network capacity")
    logger.info("  - Security requirements")


async def example_rate_limit_exceeded() -> None:
    """Example of handling rate limit exceeded scenarios."""
    logger.info("=" * 60)
    logger.info("Example: Rate Limit Exceeded")
    logger.info("=" * 60)

    connection_config = ConnectionConfig(
        inbound_connection_threshold=2,  # Very low for demo
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("When rate limit is exceeded:")
    logger.info("  - Connection attempts are rejected immediately")
    logger.info("  - No connection is established")
    logger.info("  - Rate limiter resets after the time window")
    threshold = connection_config.inbound_connection_threshold
    logger.info(f"  - Current threshold: {threshold}/sec")
    logger.info("  - This protects against connection flooding attacks")

    await swarm.close()
    logger.info("Rate limit exceeded example completed\n")


async def main() -> None:
    """Run all rate limiting examples."""
    logger.info("\n" + "=" * 60)
    logger.info("Rate Limiting Examples")
    logger.info("=" * 60 + "\n")

    try:
        await example_basic_rate_limiting()
        await example_rate_limit_behavior()
        await example_custom_rate_limits()
        await example_rate_limit_exceeded()

        logger.info("=" * 60)
        logger.info("All rate limiting examples completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Example failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    trio.run(main)
