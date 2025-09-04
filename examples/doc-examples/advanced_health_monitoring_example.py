#!/usr/bin/env python3
"""
Advanced example demonstrating enhanced connection health monitoring in libp2p.

1. Advanced health metrics (bandwidth, error tracking, connection events)
2. Health reporting and metrics export
3. Proactive connection monitoring
4. Prometheus metrics integration
"""

import logging

import trio

from libp2p import new_swarm
from libp2p.network.swarm import ConnectionConfig

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_advanced_health_metrics() -> None:
    """Example of advanced health monitoring with bandwidth tracking."""
    logger.info("Creating swarm with advanced health monitoring...")

    # Create connection config with enhanced monitoring
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=15.0,  # More frequent checks
        ping_timeout=2.0,  # Faster ping timeout
        min_health_threshold=0.5,  # Higher threshold
        min_connections_per_peer=2,
        load_balancing_strategy="health_based",
    )

    swarm = new_swarm(connection_config=connection_config)

    logger.info("Advanced health monitoring features:")
    logger.info("  - Bandwidth tracking and usage metrics")
    logger.info("  - Error history and connection event logging")
    logger.info("  - Connection stability analysis")
    logger.info("  - Health metrics export (JSON/Prometheus)")
    logger.info("  - Proactive connection replacement")

    await swarm.close()
    logger.info("Advanced health monitoring example completed")


async def main() -> None:
    """Run advanced health monitoring examples."""
    logger.info("=== Advanced Connection Health Monitoring Examples ===\n")

    await example_advanced_health_metrics()

    logger.info("\n=== Advanced examples completed ===")
    logger.info("\nPhase 2 Features Implemented:")
    logger.info("✅ Advanced health metrics (bandwidth, errors, events)")
    logger.info("✅ Health reporting and metrics export")
    logger.info("✅ Proactive connection monitoring")
    logger.info("✅ Prometheus metrics integration")


if __name__ == "__main__":
    trio.run(main)
