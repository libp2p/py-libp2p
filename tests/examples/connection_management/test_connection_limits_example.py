"""
Tests for connection limits example.
"""

import pytest

from libp2p import new_swarm
from libp2p.network.config import ConnectionConfig


@pytest.mark.trio
async def test_basic_connection_limits() -> None:
    """Test basic connection limits configuration."""
    connection_config = ConnectionConfig(
        max_connections=5,
        max_connections_per_peer=2,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.max_connections == 5
    assert connection_config.max_connections_per_peer == 2

    connections = swarm.get_connections()
    assert len(connections) == 0  # No connections yet

    await swarm.close()


@pytest.mark.trio
async def test_connection_pruning_config() -> None:
    """Test connection pruning configuration."""
    connection_config = ConnectionConfig(
        max_connections=3,
        max_connections_per_peer=1,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.max_connections == 3
    assert hasattr(swarm, "connection_pruner") or hasattr(swarm, "connection_config")

    await swarm.close()


@pytest.mark.trio
async def test_dynamic_limit_adjustment() -> None:
    """Test dynamic limit adjustment."""
    connection_config = ConnectionConfig(max_connections=10)
    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.max_connections == 10

    # Adjust limit
    connection_config.max_connections = 5
    assert connection_config.max_connections == 5

    # Increase limit
    connection_config.max_connections = 20
    assert connection_config.max_connections == 20

    await swarm.close()


@pytest.mark.trio
async def test_per_peer_limits() -> None:
    """Test per-peer connection limits."""
    connection_config = ConnectionConfig(
        max_connections=100,
        max_connections_per_peer=3,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.max_connections == 100
    assert connection_config.max_connections_per_peer == 3

    await swarm.close()


@pytest.mark.trio
async def test_connection_limit_validation() -> None:
    """Test connection limit validation."""
    # Valid configuration
    connection_config = ConnectionConfig(max_connections=10)
    assert connection_config.max_connections == 10

    # Invalid: max_connections < 1 should raise error
    with pytest.raises(ValueError, match="Max connections should be at least 1"):
        ConnectionConfig(max_connections=0)

    # Invalid: max_connections_per_peer < 1 should raise error
    with pytest.raises(
        ValueError, match="Max connection per peer should be at least 1"
    ):
        ConnectionConfig(max_connections_per_peer=0)


@pytest.mark.trio
async def test_connection_limit_exceeded_config() -> None:
    """Test configuration for handling connection limit exceeded."""
    connection_config = ConnectionConfig(
        max_connections=2,
        max_incoming_pending_connections=1,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert connection_config.max_connections == 2
    assert connection_config.max_incoming_pending_connections == 1

    await swarm.close()
