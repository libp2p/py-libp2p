"""
Tests for allow/deny lists example.
"""

import pytest

from libp2p import new_swarm
from libp2p.network.config import ConnectionConfig


@pytest.mark.trio
async def test_allow_list() -> None:
    """Test allow list configuration."""
    connection_config = ConnectionConfig(
        allow_list=[
            "192.168.1.0/24",
            "10.0.0.1",
        ],
    )

    swarm = new_swarm(connection_config=connection_config)

    assert len(connection_config.allow_list) == 2
    assert "192.168.1.0/24" in connection_config.allow_list
    assert "10.0.0.1" in connection_config.allow_list

    await swarm.close()


@pytest.mark.trio
async def test_deny_list() -> None:
    """Test deny list configuration."""
    connection_config = ConnectionConfig(
        deny_list=[
            "192.168.1.100",
            "10.0.0.0/8",
        ],
    )

    swarm = new_swarm(connection_config=connection_config)

    assert len(connection_config.deny_list) == 2
    assert "192.168.1.100" in connection_config.deny_list
    assert "10.0.0.0/8" in connection_config.deny_list

    await swarm.close()


@pytest.mark.trio
async def test_cidr_blocks() -> None:
    """Test CIDR block configuration."""
    connection_config = ConnectionConfig(
        allow_list=[
            "192.168.0.0/16",
            "10.0.0.0/8",
            "172.16.0.0/12",
        ],
        deny_list=[
            "192.168.1.100/32",
            "10.0.0.0/24",
        ],
    )

    swarm = new_swarm(connection_config=connection_config)

    assert len(connection_config.allow_list) == 3
    assert len(connection_config.deny_list) == 2

    await swarm.close()


@pytest.mark.trio
async def test_precedence_rules() -> None:
    """Test allow/deny list precedence configuration."""
    connection_config = ConnectionConfig(
        allow_list=["192.168.1.0/24"],
        deny_list=["192.168.1.100"],  # This is in the allow list range
    )

    swarm = new_swarm(connection_config=connection_config)

    assert "192.168.1.0/24" in connection_config.allow_list
    assert "192.168.1.100" in connection_config.deny_list
    # Deny list should take precedence (tested in connection_gate)

    await swarm.close()


@pytest.mark.trio
async def test_production_allow_deny() -> None:
    """Test production allow/deny list configuration."""
    connection_config = ConnectionConfig(
        allow_list=[
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ],
        deny_list=[],
        max_connections=300,
    )

    swarm = new_swarm(connection_config=connection_config)

    assert len(connection_config.allow_list) == 3
    assert len(connection_config.deny_list) == 0
    assert connection_config.max_connections == 300

    await swarm.close()


@pytest.mark.trio
async def test_empty_lists() -> None:
    """Test empty allow/deny lists."""
    connection_config = ConnectionConfig(
        allow_list=[],
        deny_list=[],
    )

    swarm = new_swarm(connection_config=connection_config)

    assert len(connection_config.allow_list) == 0
    assert len(connection_config.deny_list) == 0

    await swarm.close()


@pytest.mark.trio
async def test_connection_gate_integration() -> None:
    """Test that connection gate is properly configured."""
    connection_config = ConnectionConfig(
        allow_list=["10.0.0.0/8"],
        deny_list=["192.168.1.100"],
    )

    swarm = new_swarm(connection_config=connection_config)

    # Connection gate should be configured with allow/deny lists
    # The actual filtering is tested in connection_gate tests
    assert connection_config.allow_list
    assert connection_config.deny_list

    await swarm.close()
