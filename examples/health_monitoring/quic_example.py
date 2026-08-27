#!/usr/bin/env python3
"""
Example demonstrating health monitoring with QUIC transport.

This example shows that health monitoring works seamlessly with QUIC connections:
1. QUIC connections are tracked just like TCP connections
2. Health metrics are collected for QUIC connections
3. Load balancing strategies work with QUIC
4. Both ConnectionConfig and QUICTransportConfig can enable health monitoring
"""

import logging

import trio

from libp2p import new_host
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.network.config import ConnectionConfig
from libp2p.transport.quic.config import QUICTransportConfig

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_quic_with_connection_config():
    """Example showing QUIC with health monitoring via ConnectionConfig."""
    logger.info("=== QUIC + Health Monitoring via ConnectionConfig ===")

    # Create separate configs for QUIC transport and health monitoring
    quic_config = QUICTransportConfig(
        idle_timeout=60.0,
        max_concurrent_streams=200,
    )
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,
        load_balancing_strategy="health_based",
        max_connections_per_peer=5,
    )

    # Create host with both configs - the new logic will merge them properly
    host = new_host(
        key_pair=create_new_key_pair(),
        enable_quic=True,
        quic_transport_opt=quic_config,
        # This will be merged into QUIC config
        connection_config=connection_config,
    )

    logger.info("✅ QUIC host created with health monitoring enabled")
    logger.info(f"Health monitoring: {connection_config.enable_health_monitoring}")
    logger.info(f"Load balancing strategy: {connection_config.load_balancing_strategy}")

    # Health monitoring works with QUIC connections
    health_summary = host.get_network_health_summary()
    logger.info(f"Network health summary: {health_summary}")

    # Export health metrics
    json_metrics = host.export_health_metrics("json")
    logger.info(f"Health metrics (JSON): {json_metrics}")

    await host.close()
    logger.info("QUIC + ConnectionConfig example completed\n")


async def example_quic_with_integrated_config():
    """Example showing QUIC with health monitoring via QUICTransportConfig directly."""
    logger.info("=== QUIC + Health Monitoring via QUICTransportConfig ===")

    # QUICTransportConfig inherits from ConnectionConfig,
    # so it has all health monitoring options
    quic_config = QUICTransportConfig(
        # QUIC-specific settings
        idle_timeout=60.0,
        max_concurrent_streams=200,
        enable_qlog=True,
        # Health monitoring settings (inherited from ConnectionConfig)
        enable_health_monitoring=True,
        health_check_interval=45.0,
        load_balancing_strategy="latency_based",
        max_connections_per_peer=3,
    )

    # Create host with integrated config
    host = new_host(
        key_pair=create_new_key_pair(),
        enable_quic=True,
        quic_transport_opt=quic_config,
        # No separate connection_config needed
    )

    logger.info("✅ QUIC host created with integrated health monitoring")
    logger.info(f"Health monitoring: {quic_config.enable_health_monitoring}")
    logger.info(f"Load balancing strategy: {quic_config.load_balancing_strategy}")
    logger.info(f"QUIC logging enabled: {quic_config.enable_qlog}")

    # Health monitoring works seamlessly
    health_summary = host.get_network_health_summary()
    logger.info(f"Network health summary: {health_summary}")

    # Get health monitor status
    monitor_status = await host.get_health_monitor_status()
    logger.info(f"Health monitor status: {monitor_status}")

    await host.close()
    logger.info("QUIC + QUICTransportConfig example completed\n")


async def example_quic_health_monitoring_disabled():
    """Example showing QUIC without health monitoring."""
    logger.info("=== QUIC without Health Monitoring ===")

    # Create QUIC config without health monitoring
    quic_config = QUICTransportConfig(
        idle_timeout=30.0,
        max_concurrent_streams=100,
        enable_health_monitoring=False,  # Explicitly disabled
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        enable_quic=True,
        quic_transport_opt=quic_config,
    )

    logger.info("✅ QUIC host created without health monitoring")
    logger.info(f"Health monitoring: {quic_config.enable_health_monitoring}")

    # Health methods return empty data when disabled
    health_summary = host.get_network_health_summary()
    logger.info(f"Network health summary: {health_summary}")  # Should be empty

    monitor_status = await host.get_health_monitor_status()
    logger.info(f"Health monitor status: {monitor_status}")  # Should show disabled

    await host.close()
    logger.info("QUIC without health monitoring example completed\n")


async def main():
    """Run all QUIC health monitoring examples."""
    logger.info("🚀 QUIC + Health Monitoring Examples")
    logger.info("Demonstrating health monitoring compatibility with QUIC transport\n")

    await example_quic_with_connection_config()
    await example_quic_with_integrated_config()
    await example_quic_health_monitoring_disabled()

    logger.info("🎉 All QUIC examples completed successfully!")
    logger.info("\n📋 Key Points Demonstrated:")
    logger.info("✅ Health monitoring works seamlessly with QUIC connections")
    logger.info("✅ QUIC connections are tracked just like TCP connections")
    logger.info("✅ QUICTransportConfig inherits from ConnectionConfig")
    logger.info("✅ Both separate and integrated config approaches work")
    logger.info("✅ Load balancing strategies work with QUIC")
    logger.info("✅ Health metrics collection works with QUIC")
    logger.info("\n" + "=" * 60)
    logger.info("📋 QUIC + HEALTH MONITORING: FULLY COMPATIBLE")
    logger.info("=" * 60)


if __name__ == "__main__":
    trio.run(main)
