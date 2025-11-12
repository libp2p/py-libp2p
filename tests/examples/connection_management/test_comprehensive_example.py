"""
Tests for comprehensive connection management example.
"""

import pytest

from libp2p import new_swarm
from libp2p.network.config import ConnectionConfig


@pytest.mark.trio
async def test_production_configuration() -> None:
    """Test production-ready configuration."""
    connection_config = ConnectionConfig(
        max_connections=300,
        max_connections_per_peer=3,
        max_parallel_dials=100,
        max_dial_queue_length=500,
        max_incoming_pending_connections=10,
        inbound_connection_threshold=5,
        allow_list=["10.0.0.0/8", "192.168.0.0/16"],
        deny_list=[],
        dial_timeout=10.0,
        connection_close_timeout=1.0,
        reconnect_retries=5,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.max_connections == 300
    assert connection_config.max_connections_per_peer == 3
    assert connection_config.inbound_connection_threshold == 5
    assert len(connection_config.allow_list) == 2

    connections = swarm.get_connections()
    assert len(connections) == 0

    await swarm.close()


@pytest.mark.trio
async def test_high_performance_config() -> None:
    """Test high-performance configuration."""
    connection_config = ConnectionConfig(
        max_connections=1000,
        max_connections_per_peer=5,
        max_parallel_dials=200,
        max_dial_queue_length=1000,
        inbound_connection_threshold=20,
        max_incoming_pending_connections=50,
        dial_timeout=5.0,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.max_connections == 1000
    assert connection_config.max_parallel_dials == 200
    assert connection_config.inbound_connection_threshold == 20

    await swarm.close()


@pytest.mark.trio
async def test_restrictive_config() -> None:
    """Test restrictive/secure configuration."""
    connection_config = ConnectionConfig(
        max_connections=50,
        max_connections_per_peer=1,
        max_parallel_dials=10,
        inbound_connection_threshold=2,
        allow_list=["10.0.0.0/8"],
        deny_list=[],
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.max_connections == 50
    assert connection_config.max_connections_per_peer == 1
    assert connection_config.inbound_connection_threshold == 2
    assert len(connection_config.allow_list) == 1

    await swarm.close()


@pytest.mark.trio
async def test_monitoring_setup() -> None:
    """Test connection monitoring setup."""
    connection_config = ConnectionConfig(max_connections=100)
    swarm = new_swarm(connection_config=connection_config)

    # Get connection statistics
    connections = swarm.get_connections()
    assert len(connections) == 0

    # Calculate utilization
    utilization = len(connections) / connection_config.max_connections * 100
    assert utilization == 0.0

    # Get connections map if available
    if hasattr(swarm, "get_connections_map"):
        connections_map = swarm.get_connections_map()
        assert isinstance(connections_map, dict)
        assert len(connections_map) == 0

    await swarm.close()


@pytest.mark.trio
async def test_configuration_validation() -> None:
    """Test that all configurations are valid."""
    configs = [
        # Production config
        ConnectionConfig(
            max_connections=300,
            max_connections_per_peer=3,
            inbound_connection_threshold=5,
        ),
        # High-performance config
        ConnectionConfig(
            max_connections=1000,
            max_parallel_dials=200,
            inbound_connection_threshold=20,
        ),
        # Restrictive config
        ConnectionConfig(
            max_connections=50,
            max_connections_per_peer=1,
            inbound_connection_threshold=2,
        ),
    ]

    for config in configs:
        swarm = new_swarm(connection_config=config)
        assert config.max_connections > 0
        await swarm.close()


@pytest.mark.trio
async def test_best_practices_validation() -> None:
    """Test that configurations follow best practices."""
    # Good configuration
    good_config = ConnectionConfig(
        max_connections=300,  # Reasonable limit
        max_connections_per_peer=3,  # Prevents abuse
        inbound_connection_threshold=5,  # Balanced
        allow_list=["10.0.0.0/8"],  # Specific network
    )

    assert good_config.max_connections > 0
    assert good_config.max_connections_per_peer > 0
    assert good_config.inbound_connection_threshold > 0
    assert len(good_config.allow_list) > 0

    swarm = new_swarm(connection_config=good_config)
    await swarm.close()
