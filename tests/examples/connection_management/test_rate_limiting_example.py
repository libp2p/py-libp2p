"""
Tests for rate limiting example.
"""

import pytest

from libp2p import new_swarm
from libp2p.network.config import ConnectionConfig


@pytest.mark.trio
async def test_basic_rate_limiting() -> None:
    """Test basic rate limiting configuration."""
    connection_config = ConnectionConfig(
        inbound_connection_threshold=5,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.inbound_connection_threshold == 5

    await swarm.close()


@pytest.mark.trio
async def test_rate_limit_behavior() -> None:
    """Test rate limit behavior configuration."""
    connection_config = ConnectionConfig(
        inbound_connection_threshold=3,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.inbound_connection_threshold == 3
    assert hasattr(swarm, "connection_gate") or hasattr(swarm, "connection_config")

    await swarm.close()


@pytest.mark.trio
async def test_custom_rate_limits() -> None:
    """Test custom rate limit configurations."""
    # High-traffic scenario
    high_traffic_config = ConnectionConfig(
        inbound_connection_threshold=20,
        max_incoming_pending_connections=50,
    )

    assert high_traffic_config.inbound_connection_threshold == 20
    assert high_traffic_config.max_incoming_pending_connections == 50

    # Low-traffic scenario
    low_traffic_config = ConnectionConfig(
        inbound_connection_threshold=2,
        max_incoming_pending_connections=5,
    )

    assert low_traffic_config.inbound_connection_threshold == 2
    assert low_traffic_config.max_incoming_pending_connections == 5


@pytest.mark.trio
async def test_rate_limit_exceeded_config() -> None:
    """Test configuration for handling rate limit exceeded."""
    connection_config = ConnectionConfig(
        inbound_connection_threshold=2,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.inbound_connection_threshold == 2

    await swarm.close()


@pytest.mark.trio
async def test_rate_limit_validation() -> None:
    """Test rate limit configuration validation."""
    # Valid configuration
    config = ConnectionConfig(inbound_connection_threshold=5)
    assert config.inbound_connection_threshold == 5

    # Zero threshold (edge case)
    config = ConnectionConfig(inbound_connection_threshold=0)
    assert config.inbound_connection_threshold == 0

    # High threshold
    config = ConnectionConfig(inbound_connection_threshold=100)
    assert config.inbound_connection_threshold == 100
