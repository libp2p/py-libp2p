#!/usr/bin/env python3
"""
Example demonstrating the enhanced Swarm with retry logic, exponential backoff,
and multi-connection support.

This example shows how to:
1. Configure retry behavior with exponential backoff
2. Enable multi-connection support with connection pooling
3. Use different load balancing strategies
4. Maintain backward compatibility
"""

import asyncio
import logging

from libp2p import new_swarm
from libp2p.network.swarm import ConnectionConfig, RetryConfig

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_basic_enhanced_swarm() -> None:
    """Example of basic enhanced Swarm usage."""
    logger.info("Creating enhanced Swarm with default configuration...")

    # Create enhanced swarm with default retry and connection config
    swarm = new_swarm()
    # Use default configuration values directly
    default_retry = RetryConfig()
    default_connection = ConnectionConfig()

    logger.info(f"Swarm created with peer ID: {swarm.get_peer_id()}")
    logger.info(f"Retry config: max_retries={default_retry.max_retries}")
    logger.info(
        f"Connection config: max_connections_per_peer="
        f"{default_connection.max_connections_per_peer}"
    )
    logger.info(f"Connection pool enabled: {default_connection.enable_connection_pool}")

    await swarm.close()
    logger.info("Basic enhanced Swarm example completed")


async def example_custom_retry_config() -> None:
    """Example of custom retry configuration."""
    logger.info("Creating enhanced Swarm with custom retry configuration...")

    # Custom retry configuration for aggressive retry behavior
    retry_config = RetryConfig(
        max_retries=5,  # More retries
        initial_delay=0.05,  # Faster initial retry
        max_delay=10.0,  # Lower max delay
        backoff_multiplier=1.5,  # Less aggressive backoff
        jitter_factor=0.2,  # More jitter
    )

    # Create swarm with custom retry config
    swarm = new_swarm(retry_config=retry_config)

    logger.info("Custom retry config applied:")
    logger.info(f"  Max retries: {retry_config.max_retries}")
    logger.info(f"  Initial delay: {retry_config.initial_delay}s")
    logger.info(f"  Max delay: {retry_config.max_delay}s")
    logger.info(f"  Backoff multiplier: {retry_config.backoff_multiplier}")
    logger.info(f"  Jitter factor: {retry_config.jitter_factor}")

    await swarm.close()
    logger.info("Custom retry config example completed")


async def example_custom_connection_config() -> None:
    """Example of custom connection configuration."""
    logger.info("Creating enhanced Swarm with custom connection configuration...")

    # Custom connection configuration for high-performance scenarios
    connection_config = ConnectionConfig(
        max_connections_per_peer=5,  # More connections per peer
        connection_timeout=60.0,  # Longer timeout
        enable_connection_pool=True,  # Enable connection pooling
        load_balancing_strategy="least_loaded",  # Use least loaded strategy
    )

    # Create swarm with custom connection config
    swarm = new_swarm(connection_config=connection_config)

    logger.info("Custom connection config applied:")
    logger.info(
        f"  Max connections per peer: {connection_config.max_connections_per_peer}"
    )
    logger.info(f"  Connection timeout: {connection_config.connection_timeout}s")
    logger.info(
        f"  Connection pool enabled: {connection_config.enable_connection_pool}"
    )
    logger.info(
        f"  Load balancing strategy: {connection_config.load_balancing_strategy}"
    )

    await swarm.close()
    logger.info("Custom connection config example completed")


async def example_backward_compatibility() -> None:
    """Example showing backward compatibility."""
    logger.info("Creating enhanced Swarm with backward compatibility...")

    # Disable connection pool to maintain original behavior
    connection_config = ConnectionConfig(enable_connection_pool=False)

    # Create swarm with connection pool disabled
    swarm = new_swarm(connection_config=connection_config)

    logger.info("Backward compatibility mode:")
    logger.info(
        f"  Connection pool enabled: {connection_config.enable_connection_pool}"
    )
    logger.info(f"  Connections dict type: {type(swarm.connections)}")
    logger.info("  Retry logic still available: 3 max retries")

    await swarm.close()
    logger.info("Backward compatibility example completed")


async def example_production_ready_config() -> None:
    """Example of production-ready configuration."""
    logger.info("Creating enhanced Swarm with production-ready configuration...")

    # Production-ready retry configuration
    retry_config = RetryConfig(
        max_retries=3,  # Reasonable retry limit
        initial_delay=0.1,  # Quick initial retry
        max_delay=30.0,  # Cap exponential backoff
        backoff_multiplier=2.0,  # Standard exponential backoff
        jitter_factor=0.1,  # Small jitter to prevent thundering herd
    )

    # Production-ready connection configuration
    connection_config = ConnectionConfig(
        max_connections_per_peer=3,  # Balance between performance and resource usage
        connection_timeout=30.0,  # Reasonable timeout
        enable_connection_pool=True,  # Enable for better performance
        load_balancing_strategy="round_robin",  # Simple, predictable strategy
    )

    # Create swarm with production config
    swarm = new_swarm(retry_config=retry_config, connection_config=connection_config)

    logger.info("Production-ready configuration applied:")
    logger.info(
        f"  Retry: {retry_config.max_retries} retries, "
        f"{retry_config.max_delay}s max delay"
    )
    logger.info(f"  Connections: {connection_config.max_connections_per_peer} per peer")
    logger.info(f"  Load balancing: {connection_config.load_balancing_strategy}")

    await swarm.close()
    logger.info("Production-ready configuration example completed")


async def main() -> None:
    """Run all examples."""
    logger.info("Enhanced Swarm Examples")
    logger.info("=" * 50)

    try:
        await example_basic_enhanced_swarm()
        logger.info("-" * 30)

        await example_custom_retry_config()
        logger.info("-" * 30)

        await example_custom_connection_config()
        logger.info("-" * 30)

        await example_backward_compatibility()
        logger.info("-" * 30)

        await example_production_ready_config()
        logger.info("-" * 30)

        logger.info("All examples completed successfully!")

    except Exception as e:
        logger.error(f"Example failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
