#!/usr/bin/env python3
"""
Example demonstrating multiple connections per peer support in libp2p.

This example shows how to:
1. Configure multiple connections per peer
2. Use different load balancing strategies
3. Access multiple connections through the new API
4. Maintain backward compatibility
5. Use the new address paradigm for network configuration
"""

import logging

import trio

from libp2p import new_swarm
from libp2p.network.swarm import ConnectionConfig, RetryConfig
from libp2p.utils import get_available_interfaces, get_optimal_binding_address

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_basic_multiple_connections() -> None:
    """Example of basic multiple connections per peer usage."""
    logger.info("Creating swarm with multiple connections support...")

    # Create swarm with default configuration
    swarm = new_swarm()
    default_connection = ConnectionConfig()

    logger.info(f"Swarm created with peer ID: {swarm.get_peer_id()}")
    logger.info(
        f"Connection config: max_connections_per_peer="
        f"{default_connection.max_connections_per_peer}"
    )

    await swarm.close()
    logger.info("Basic multiple connections example completed")


async def example_custom_connection_config() -> None:
    """Example of custom connection configuration."""
    logger.info("Creating swarm with custom connection configuration...")

    # Custom connection configuration for high-performance scenarios
    connection_config = ConnectionConfig(
        max_connections_per_peer=5,  # More connections per peer
        connection_timeout=60.0,  # Longer timeout
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
        f"  Load balancing strategy: {connection_config.load_balancing_strategy}"
    )

    await swarm.close()
    logger.info("Custom connection config example completed")


async def example_multiple_connections_api() -> None:
    """Example of using the new multiple connections API."""
    logger.info("Demonstrating multiple connections API...")

    connection_config = ConnectionConfig(
        max_connections_per_peer=3, load_balancing_strategy="round_robin"
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Multiple connections API features:")
    logger.info("  - dial_peer() returns list[INetConn]")
    logger.info("  - get_connections(peer_id) returns list[INetConn]")
    logger.info("  - get_connections_map() returns dict[ID, list[INetConn]]")
    logger.info(
        "  - get_connection(peer_id) returns INetConn | None (backward compatibility)"
    )

    await swarm.close()
    logger.info("Multiple connections API example completed")


async def example_backward_compatibility() -> None:
    """Example of backward compatibility features."""
    logger.info("Demonstrating backward compatibility...")

    swarm = new_swarm()

    logger.info("Backward compatibility features:")
    logger.info("  - connections_legacy property provides 1:1 mapping")
    logger.info("  - get_connection() method for single connection access")
    logger.info("  - Existing code continues to work")

    await swarm.close()
    logger.info("Backward compatibility example completed")


async def example_network_address_paradigm() -> None:
    """Example of using the new address paradigm with multiple connections."""
    logger.info("Demonstrating network address paradigm...")

    # Get available interfaces using the new paradigm
    port = 8000  # Example port
    available_interfaces = get_available_interfaces(port)
    logger.info(f"Available interfaces: {available_interfaces}")

    # Get optimal binding address
    optimal_address = get_optimal_binding_address(port)
    logger.info(f"Optimal binding address: {optimal_address}")

    # Create connection config for multiple connections with network awareness
    connection_config = ConnectionConfig(
        max_connections_per_peer=3, load_balancing_strategy="round_robin"
    )

    # Create swarm with address paradigm
    swarm = new_swarm(connection_config=connection_config)

    logger.info("Network address paradigm features:")
    logger.info("  - get_available_interfaces() for interface discovery")
    logger.info("  - get_optimal_binding_address() for smart address selection")
    logger.info("  - Multiple connections with proper network binding")

    await swarm.close()
    logger.info("Network address paradigm example completed")


async def example_production_ready_config() -> None:
    """Example of production-ready configuration."""
    logger.info("Creating swarm with production-ready configuration...")

    # Get optimal network configuration using the new paradigm
    port = 8001  # Example port
    optimal_address = get_optimal_binding_address(port)
    logger.info(f"Using optimal binding address: {optimal_address}")

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
    logger.info("Multiple Connections Per Peer Examples")
    logger.info("=" * 50)

    try:
        await example_basic_multiple_connections()
        logger.info("-" * 30)

        await example_custom_connection_config()
        logger.info("-" * 30)

        await example_multiple_connections_api()
        logger.info("-" * 30)

        await example_backward_compatibility()
        logger.info("-" * 30)

        await example_network_address_paradigm()
        logger.info("-" * 30)

        await example_production_ready_config()
        logger.info("-" * 30)

        logger.info("All examples completed successfully!")

    except Exception as e:
        logger.error(f"Example failed: {e}")
        raise


if __name__ == "__main__":
    trio.run(main)
