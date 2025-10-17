"""
Integration tests for health monitoring with Swarm.

Tests the integration of health monitoring features with the Swarm class,
including load balancing strategies and connection lifecycle management.
"""

from typing import cast
from unittest.mock import Mock

import pytest
import trio

from libp2p.abc import INetConn, INetStream
from libp2p.network.config import ConnectionConfig
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID


class MockConnection(INetConn):
    """Mock connection for testing."""

    def __init__(self, peer_id: ID, is_closed: bool = False) -> None:
        self.peer_id = peer_id
        self._is_closed = is_closed
        self.streams: set[INetStream] = set()
        self.muxed_conn = Mock()
        self.muxed_conn.peer_id = peer_id
        self.event_started = trio.Event()

    async def close(self):
        self._is_closed = True

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    async def new_stream(self) -> INetStream:
        mock_stream = Mock(spec=INetStream)
        mock_stream.reset = Mock()
        mock_stream.close = Mock()
        self.streams.add(mock_stream)
        return mock_stream

    def get_streams(self) -> tuple[INetStream, ...]:
        return tuple(self.streams)

    def get_transport_addresses(self):
        return []


@pytest.mark.trio
async def test_swarm_health_monitoring_initialization_enabled() -> None:
    """Test swarm initializes health monitoring when enabled."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,
        load_balancing_strategy="health_based",
    )

    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    # Verify health monitoring initialized
    assert hasattr(swarm, "health_data")
    assert isinstance(swarm.health_data, dict)
    assert swarm._is_health_monitoring_enabled is True
    assert hasattr(swarm, "_health_monitor")


@pytest.mark.trio
async def test_swarm_health_monitoring_initialization_disabled() -> None:
    """Test swarm without health monitoring."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(enable_health_monitoring=False)

    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    # Verify health monitoring not enabled
    assert swarm._is_health_monitoring_enabled is False


@pytest.mark.trio
async def test_initialize_connection_health() -> None:
    """Test health initialization for new connection."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(
        enable_health_monitoring=True,
        latency_weight=0.5,
        success_rate_weight=0.3,
        stability_weight=0.2,
    )

    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    # Create connection
    conn_peer_id = ID(b"QmPeer1")
    conn = MockConnection(conn_peer_id)

    # Initialize health
    swarm.initialize_connection_health(conn_peer_id, conn)

    # Verify health data created
    assert conn_peer_id in swarm.health_data
    assert conn in swarm.health_data[conn_peer_id]

    health = swarm.health_data[conn_peer_id][conn]
    assert health.health_score == 1.0
    assert health.ping_success_rate == 1.0
    assert health.latency_weight == 0.5
    assert health.success_rate_weight == 0.3
    assert health.stability_weight == 0.2


@pytest.mark.trio
async def test_cleanup_connection_health() -> None:
    """Test health cleanup on connection close."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(enable_health_monitoring=True)
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn = MockConnection(conn_peer_id)

    # Initialize and then cleanup
    swarm.initialize_connection_health(conn_peer_id, conn)
    assert conn_peer_id in swarm.health_data

    swarm.cleanup_connection_health(conn_peer_id, conn)

    # Verify health data removed
    assert conn_peer_id not in swarm.health_data


@pytest.mark.trio
async def test_cleanup_connection_health_multiple_connections() -> None:
    """Test cleanup doesn't remove peer if other connections exist."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(enable_health_monitoring=True)
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn1 = MockConnection(conn_peer_id)
    conn2 = MockConnection(conn_peer_id)

    # Initialize both connections
    swarm.initialize_connection_health(conn_peer_id, conn1)
    swarm.initialize_connection_health(conn_peer_id, conn2)

    # Cleanup first connection
    swarm.cleanup_connection_health(conn_peer_id, conn1)

    # Peer should still be in health_data (conn2 remains)
    assert conn_peer_id in swarm.health_data
    assert conn1 not in swarm.health_data[conn_peer_id]
    assert conn2 in swarm.health_data[conn_peer_id]

    # Cleanup second connection
    swarm.cleanup_connection_health(conn_peer_id, conn2)

    # Now peer should be removed
    assert conn_peer_id not in swarm.health_data


@pytest.mark.trio
async def test_select_connection_round_robin() -> None:
    """Test round-robin load balancing strategy."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(load_balancing_strategy="round_robin")
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn1 = MockConnection(conn_peer_id)
    conn2 = MockConnection(conn_peer_id)
    conn3 = MockConnection(conn_peer_id)

    connections = [conn1, conn2, conn3]

    # Select connections in round-robin fashion
    conn_list = cast("list[INetConn]", connections)
    selected1 = swarm._select_connection(conn_list, conn_peer_id)
    selected2 = swarm._select_connection(conn_list, conn_peer_id)
    selected3 = swarm._select_connection(conn_list, conn_peer_id)
    selected4 = swarm._select_connection(conn_list, conn_peer_id)

    # Should cycle through connections
    assert selected1 in connections
    assert selected2 in connections
    assert selected3 in connections
    # Fourth selection should wrap around
    assert selected4 == selected1


@pytest.mark.trio
async def test_select_connection_least_loaded() -> None:
    """Test least-loaded load balancing strategy."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(load_balancing_strategy="least_loaded")
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn1 = MockConnection(conn_peer_id)
    conn2 = MockConnection(conn_peer_id)
    conn3 = MockConnection(conn_peer_id)

    # Add different numbers of streams
    await conn1.new_stream()
    await conn1.new_stream()  # 2 streams
    await conn2.new_stream()  # 1 stream
    # conn3 has 0 streams

    connections = [conn1, conn2, conn3]

    # Select connection
    conn_list = cast("list[INetConn]", connections)
    selected = swarm._select_connection(conn_list, conn_peer_id)

    # Should select conn3 (least loaded)
    assert selected == conn3


@pytest.mark.trio
async def test_select_connection_health_based() -> None:
    """Test health-based load balancing strategy."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(
        enable_health_monitoring=True, load_balancing_strategy="health_based"
    )
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn1 = MockConnection(conn_peer_id)
    conn2 = MockConnection(conn_peer_id)
    conn3 = MockConnection(conn_peer_id)

    # Initialize health with different scores
    swarm.initialize_connection_health(conn_peer_id, conn1)
    swarm.initialize_connection_health(conn_peer_id, conn2)
    swarm.initialize_connection_health(conn_peer_id, conn3)

    swarm.health_data[conn_peer_id][conn1].health_score = 0.5
    swarm.health_data[conn_peer_id][conn2].health_score = 0.9  # Best
    swarm.health_data[conn_peer_id][conn3].health_score = 0.7

    connections = [conn1, conn2, conn3]

    # Select connection
    conn_list = cast("list[INetConn]", connections)
    selected = swarm._select_connection(conn_list, conn_peer_id)

    # Should select conn2 (highest health score)
    assert selected == conn2


@pytest.mark.trio
async def test_select_connection_health_based_fallback() -> None:
    """Test health-based strategy falls back when no health data."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(
        enable_health_monitoring=True, load_balancing_strategy="health_based"
    )
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn1 = MockConnection(conn_peer_id)
    conn2 = MockConnection(conn_peer_id)
    conn3 = MockConnection(conn_peer_id)

    # Add streams to create different loads
    await conn1.new_stream()
    await conn1.new_stream()
    await conn2.new_stream()
    # conn3 has no streams

    connections = [conn1, conn2, conn3]

    # Select connection (no health data available)
    conn_list = cast("list[INetConn]", connections)
    selected = swarm._select_connection(conn_list, conn_peer_id)

    # Should fall back to least_loaded and select conn3
    assert selected == conn3


@pytest.mark.trio
async def test_select_connection_latency_based() -> None:
    """Test latency-based load balancing strategy."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(
        enable_health_monitoring=True, load_balancing_strategy="latency_based"
    )
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn1 = MockConnection(conn_peer_id)
    conn2 = MockConnection(conn_peer_id)
    conn3 = MockConnection(conn_peer_id)

    # Initialize health with different latencies
    swarm.initialize_connection_health(conn_peer_id, conn1)
    swarm.initialize_connection_health(conn_peer_id, conn2)
    swarm.initialize_connection_health(conn_peer_id, conn3)

    swarm.health_data[conn_peer_id][conn1].ping_latency = 100.0
    swarm.health_data[conn_peer_id][conn2].ping_latency = 20.0  # Lowest
    swarm.health_data[conn_peer_id][conn3].ping_latency = 50.0

    connections = [conn1, conn2, conn3]

    # Select connection
    conn_list = cast("list[INetConn]", connections)
    selected = swarm._select_connection(conn_list, conn_peer_id)

    # Should select conn2 (lowest latency)
    assert selected == conn2


@pytest.mark.trio
async def test_select_connection_latency_based_fallback() -> None:
    """Test latency-based strategy falls back when no health data."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(
        enable_health_monitoring=True, load_balancing_strategy="latency_based"
    )
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn1 = MockConnection(conn_peer_id)
    conn2 = MockConnection(conn_peer_id)

    # Add different loads
    await conn1.new_stream()
    # conn2 has no streams

    connections = [conn1, conn2]

    # Select connection (no health data)
    conn_list = cast("list[INetConn]", connections)
    selected = swarm._select_connection(conn_list, conn_peer_id)

    # Should fall back to least_loaded and select conn2
    assert selected == conn2


@pytest.mark.trio
async def test_select_connection_unknown_strategy_raises_error() -> None:
    """Test unknown strategy raises ValueError during config creation."""
    # The validation happens in ConnectionConfig.__post_init__
    # So the error is raised when creating the config, not when selecting
    with pytest.raises(ValueError, match="Load balancing strategy must be one of"):
        ConnectionConfig(load_balancing_strategy="unknown_strategy")


@pytest.mark.trio
async def test_health_monitoring_disabled_no_error() -> None:
    """Test health operations safe when monitoring disabled."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(enable_health_monitoring=False)
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn = MockConnection(conn_peer_id)

    # These should not raise errors
    swarm.initialize_connection_health(conn_peer_id, conn)
    swarm.cleanup_connection_health(conn_peer_id, conn)


@pytest.mark.trio
async def test_is_health_monitoring_enabled_property() -> None:
    """Test _is_health_monitoring_enabled property."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    # Enabled
    config_enabled = ConnectionConfig(enable_health_monitoring=True)
    swarm_enabled = Swarm(
        peer_id, peerstore, upgrader, transport, connection_config=config_enabled
    )
    assert swarm_enabled._is_health_monitoring_enabled is True

    # Disabled
    config_disabled = ConnectionConfig(enable_health_monitoring=False)
    swarm_disabled = Swarm(
        peer_id, peerstore, upgrader, transport, connection_config=config_disabled
    )
    assert swarm_disabled._is_health_monitoring_enabled is False


@pytest.mark.trio
async def test_multiple_peers_health_tracking() -> None:
    """Test health tracking for multiple peers simultaneously."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(enable_health_monitoring=True)
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    # Create connections to multiple peers
    peer1 = ID(b"QmPeer1")
    peer2 = ID(b"QmPeer2")
    peer3 = ID(b"QmPeer3")

    conn1a = MockConnection(peer1)
    conn1b = MockConnection(peer1)
    conn2 = MockConnection(peer2)
    conn3 = MockConnection(peer3)

    # Initialize health for all connections
    swarm.initialize_connection_health(peer1, conn1a)
    swarm.initialize_connection_health(peer1, conn1b)
    swarm.initialize_connection_health(peer2, conn2)
    swarm.initialize_connection_health(peer3, conn3)

    # Verify all tracked
    assert peer1 in swarm.health_data
    assert peer2 in swarm.health_data
    assert peer3 in swarm.health_data
    assert len(swarm.health_data[peer1]) == 2
    assert len(swarm.health_data[peer2]) == 1
    assert len(swarm.health_data[peer3]) == 1


@pytest.mark.trio
async def test_connection_health_independent() -> None:
    """Test health tracking is independent per connection."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(enable_health_monitoring=True)
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn1 = MockConnection(conn_peer_id)
    conn2 = MockConnection(conn_peer_id)

    swarm.initialize_connection_health(conn_peer_id, conn1)
    swarm.initialize_connection_health(conn_peer_id, conn2)

    # Modify health of conn1
    health1 = swarm.health_data[conn_peer_id][conn1]
    health1.health_score = 0.3
    health1.ping_latency = 500.0

    # Verify conn2 health unaffected
    health2 = swarm.health_data[conn_peer_id][conn2]
    assert health2.health_score == 1.0
    assert health2.ping_latency == 0.0


@pytest.mark.trio
async def test_record_connection_event() -> None:
    """Test recording connection events when health monitoring enabled."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    config = ConnectionConfig(enable_health_monitoring=True)
    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn = MockConnection(conn_peer_id)

    swarm.initialize_connection_health(conn_peer_id, conn)

    # Record event
    swarm.record_connection_event(conn_peer_id, conn, "test_event")

    # Verify event recorded
    health = swarm.health_data[conn_peer_id][conn]
    assert len(health.connection_events) == 1
    assert health.connection_events[0][1] == "test_event"


@pytest.mark.trio
async def test_config_weights_applied_to_health() -> None:
    """Test configuration weights are applied to connection health."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    # Custom weights
    config = ConnectionConfig(
        enable_health_monitoring=True,
        latency_weight=0.6,
        success_rate_weight=0.3,
        stability_weight=0.1,
    )

    swarm = Swarm(peer_id, peerstore, upgrader, transport, connection_config=config)

    conn_peer_id = ID(b"QmPeer1")
    conn = MockConnection(conn_peer_id)

    swarm.initialize_connection_health(conn_peer_id, conn)

    health = swarm.health_data[conn_peer_id][conn]

    # Verify weights applied
    assert health.latency_weight == 0.6
    assert health.success_rate_weight == 0.3
    assert health.stability_weight == 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
