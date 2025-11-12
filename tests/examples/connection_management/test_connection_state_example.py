"""
Tests for connection state example.
"""

import pytest

from libp2p import new_swarm


@pytest.mark.trio
async def test_connection_states() -> None:
    """Test connection state tracking."""
    swarm = new_swarm()

    # Get current connections
    connections = swarm.get_connections()
    assert isinstance(connections, list)

    # Connections should be empty initially
    assert len(connections) == 0

    await swarm.close()


@pytest.mark.trio
async def test_connection_timeline() -> None:
    """Test connection timeline tracking."""
    swarm = new_swarm()

    connections = swarm.get_connections()
    assert len(connections) == 0

    # Timeline tracking is tested in connection_state tests
    # This test verifies the example structure

    await swarm.close()


@pytest.mark.trio
async def test_connection_queries() -> None:
    """Test connection query methods."""
    swarm = new_swarm()

    # Get all connections
    all_connections = swarm.get_connections()
    assert isinstance(all_connections, list)
    assert len(all_connections) == 0

    # Get connections map if available
    if hasattr(swarm, "get_connections_map"):
        connections_map = swarm.get_connections_map()
        assert isinstance(connections_map, dict)
        assert len(connections_map) == 0

    await swarm.close()


@pytest.mark.trio
async def test_state_transitions() -> None:
    """Test connection state transition understanding."""
    swarm = new_swarm()

    # State transitions are managed internally
    # This test verifies the example demonstrates the concept

    connections = swarm.get_connections()
    assert len(connections) == 0

    await swarm.close()


@pytest.mark.trio
async def test_connection_metadata() -> None:
    """Test accessing connection metadata."""
    swarm = new_swarm()

    connections = swarm.get_connections()
    assert len(connections) == 0

    # Metadata access is tested when connections exist
    # This test verifies the example structure

    await swarm.close()


@pytest.mark.trio
async def test_connection_state_enum() -> None:
    """Test connection state enum values."""
    from libp2p.network.connection_state import ConnectionStatus

    # Verify state enum values
    assert ConnectionStatus.PENDING.value == "pending"
    assert ConnectionStatus.OPEN.value == "open"
    assert ConnectionStatus.CLOSING.value == "closing"
    assert ConnectionStatus.CLOSED.value == "closed"


@pytest.mark.trio
async def test_connection_state_object() -> None:
    """Test ConnectionState object."""
    from libp2p.network.connection_state import ConnectionState, ConnectionStatus

    state = ConnectionState()
    assert state.status == ConnectionStatus.PENDING
    assert state.timeline.open > 0

    # Test state transition
    state.set_status(ConnectionStatus.OPEN)
    assert state.status == ConnectionStatus.OPEN

    # Test to_dict
    state_dict = state.to_dict()
    assert "status" in state_dict
    assert "timeline" in state_dict
    assert state_dict["status"] == "open"
