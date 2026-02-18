"""
Unit tests for ConnectionHealthMonitor service.

Tests the health monitoring service, ping operations, connection health checks,
and automatic unhealthy connection replacement.
"""

import time
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import trio

from libp2p.abc import INetConn, INetStream
from libp2p.network.config import ConnectionConfig
from libp2p.network.health.data_structures import (
    ConnectionHealth,
    create_default_connection_health,
)
from libp2p.network.health.monitor import ConnectionHealthMonitor
from libp2p.peer.id import ID
from libp2p.tools.async_service import background_trio_service


class MockConnection(INetConn):
    """Mock connection for testing."""

    def __init__(
        self,
        peer_id: ID,
        is_closed: bool = False,
        fail_new_stream: bool = False,
        stream_timeout: bool = False,
    ) -> None:
        self.peer_id = peer_id
        self._is_closed = is_closed
        self._fail_new_stream = fail_new_stream
        self._stream_timeout = stream_timeout
        self.streams: set[INetStream] = set()
        self.muxed_conn = Mock()
        self.muxed_conn.peer_id = peer_id
        self.event_started = trio.Event()
        self.new_stream_called = False
        self.close_called = False

    async def close(self) -> None:
        self._is_closed = True
        self.close_called = True

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    async def new_stream(self) -> INetStream:
        self.new_stream_called = True

        if self._fail_new_stream:
            raise Exception("Mock stream creation failure")

        if self._stream_timeout:
            # Simulate timeout by sleeping forever
            await trio.sleep_forever()

        # Create mock stream
        mock_stream = Mock(spec=INetStream)
        mock_stream.reset = AsyncMock()
        mock_stream.close = AsyncMock()
        self.streams.add(mock_stream)
        return mock_stream

    def get_streams(self) -> tuple[INetStream, ...]:
        """Return all streams associated with this connection."""
        return tuple(self.streams)

    def get_transport_addresses(self) -> list[Any]:  # type: ignore[override]
        return []


class MockSwarm:
    """Mock Swarm for testing health monitor."""

    def __init__(self, config: ConnectionConfig | None = None) -> None:
        self.connection_config = config or ConnectionConfig(
            enable_health_monitoring=True
        )
        self.connections: dict[ID, list[INetConn]] = {}
        self.health_data: dict[ID, dict[INetConn, ConnectionHealth]] = {}
        self._health_monitor: ConnectionHealthMonitor | None = None
        self.initialize_connection_health_called = 0
        self.cleanup_connection_health_called = 0
        self.dial_peer_replacement_called = 0

    @property
    def _is_health_monitoring_enabled(self) -> bool:
        return self.connection_config.enable_health_monitoring

    def initialize_connection_health(self, peer_id: ID, connection: INetConn) -> None:
        """Initialize health tracking for a connection."""
        self.initialize_connection_health_called += 1
        if peer_id not in self.health_data:
            self.health_data[peer_id] = {}
        self.health_data[peer_id][connection] = create_default_connection_health()

    def cleanup_connection_health(self, peer_id: ID, connection: INetConn) -> None:
        """Clean up health tracking for a connection."""
        self.cleanup_connection_health_called += 1
        if peer_id in self.health_data and connection in self.health_data[peer_id]:
            del self.health_data[peer_id][connection]
            if not self.health_data[peer_id]:
                del self.health_data[peer_id]

    async def dial_peer_replacement(self, peer_id: ID) -> INetConn | None:
        """Mock replacement connection dialing."""
        self.dial_peer_replacement_called += 1
        # Return a new mock connection
        new_conn = MockConnection(peer_id)
        if peer_id not in self.connections:
            self.connections[peer_id] = []
        self.connections[peer_id].append(new_conn)
        return new_conn


@pytest.mark.trio
async def test_health_monitor_initialization() -> None:
    """Test ConnectionHealthMonitor initialization."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,
        ping_timeout=5.0,
    )
    swarm = MockSwarm(config)
    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    assert monitor.swarm is swarm  # type: ignore[comparison-overlap]
    assert monitor.config is config
    assert not monitor._monitoring_task_started.is_set()
    assert not monitor._stop_monitoring.is_set()


@pytest.mark.trio
async def test_health_monitor_disabled() -> None:
    """Test monitor does nothing when health monitoring disabled."""
    config = ConnectionConfig(enable_health_monitoring=False)
    swarm = MockSwarm(config)
    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Run the monitor (should exit immediately)
    with trio.fail_after(1.0):  # Should complete quickly
        async with background_trio_service(monitor):
            # Give it a moment to start
            await trio.sleep(0.1)
            # Service should have exited without doing anything


@pytest.mark.trio
async def test_health_monitor_starts_with_initial_delay() -> None:
    """Test monitoring task starts after initial delay."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_initial_delay=0.1,
        health_check_interval=10.0,
    )
    swarm = MockSwarm(config)
    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    async with trio.open_nursery() as nursery:
        nursery.start_soon(monitor.run)

        # Wait for monitoring task to start
        with trio.fail_after(1.0):
            await monitor._monitoring_task_started.wait()

        # Verify monitoring task started (delay honored by implementation)
        assert monitor._monitoring_task_started.is_set()

        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_check_all_connections() -> None:
    """Test checking health of all connections."""
    config = ConnectionConfig(enable_health_monitoring=True, health_warmup_window=0.0)
    swarm = MockSwarm(config)

    # Create multiple peers with connections
    peer1 = ID(b"peer1")
    peer2 = ID(b"peer2")
    conn1 = MockConnection(peer1)
    conn2 = MockConnection(peer1)
    conn3 = MockConnection(peer2)

    swarm.connections = {peer1: [conn1, conn2], peer2: [conn3]}

    # Initialize health data
    swarm.initialize_connection_health(peer1, conn1)
    swarm.initialize_connection_health(peer1, conn2)
    swarm.initialize_connection_health(peer2, conn3)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Check all connections
    await monitor._check_all_connections()

    # Verify new_stream was called for each connection (ping check)
    assert conn1.new_stream_called
    assert conn2.new_stream_called
    assert conn3.new_stream_called


@pytest.mark.trio
async def test_check_connection_health_warmup_skip() -> None:
    """Test warmup window skips health checks for new connections."""
    config = ConnectionConfig(
        enable_health_monitoring=True, health_warmup_window=5.0, ping_timeout=1.0
    )
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    # Initialize with recent timestamp
    swarm.initialize_connection_health(peer_id, conn)
    health = swarm.health_data[peer_id][conn]
    health.established_at = time.time()  # Just now

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Check connection health
    await monitor._check_connection_health(peer_id, conn)

    # Should skip due to warmup window
    assert not conn.new_stream_called


@pytest.mark.trio
async def test_check_connection_health_initializes_missing() -> None:
    """Test health data initialization for untracked connections."""
    config = ConnectionConfig(enable_health_monitoring=True, health_warmup_window=0.0)
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Health data doesn't exist yet
    assert peer_id not in swarm.health_data

    # Check connection health
    await monitor._check_connection_health(peer_id, conn)

    # Should have initialized health data
    assert swarm.initialize_connection_health_called == 1


@pytest.mark.trio
async def test_ping_connection_success() -> None:
    """Test successful ping operation."""
    config = ConnectionConfig(enable_health_monitoring=True, ping_timeout=1.0)
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Ping the connection
    result = await monitor._ping_connection(conn)

    assert result is True
    assert conn.new_stream_called


@pytest.mark.trio
async def test_ping_connection_failure() -> None:
    """Test failed ping operation."""
    config = ConnectionConfig(enable_health_monitoring=True, ping_timeout=1.0)
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id, fail_new_stream=True)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Ping the connection (should fail)
    result = await monitor._ping_connection(conn)

    assert result is False


@pytest.mark.trio
async def test_ping_connection_with_active_streams() -> None:
    """Test ping skipped when connection has active streams."""
    config = ConnectionConfig(enable_health_monitoring=True)
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    # Add active streams
    mock_stream = Mock(spec=INetStream)
    conn.streams.add(mock_stream)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Ping the connection
    result = await monitor._ping_connection(conn)

    # Should succeed without creating new stream
    assert result is True
    assert not conn.new_stream_called


@pytest.mark.trio
async def test_ping_connection_timeout() -> None:
    """Test ping timeout handling."""
    config = ConnectionConfig(enable_health_monitoring=True, ping_timeout=0.1)
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id, stream_timeout=True)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Ping the connection (should timeout)
    with trio.fail_after(1.0):  # Overall timeout
        result = await monitor._ping_connection(conn)

    assert result is False


@pytest.mark.trio
async def test_should_replace_connection_healthy() -> None:
    """Test healthy connection not marked for replacement."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        min_health_threshold=0.5,
        max_ping_latency=1000.0,
        min_ping_success_rate=0.7,
        max_failed_streams=5,
    )
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    # Initialize with good health
    swarm.initialize_connection_health(peer_id, conn)
    health = swarm.health_data[peer_id][conn]
    health.health_score = 0.9
    health.ping_latency = 50.0
    health.ping_success_rate = 0.95
    health.failed_streams = 0

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Check if replacement needed
    should_replace = monitor._should_replace_connection(peer_id, conn)

    assert should_replace is False


@pytest.mark.trio
async def test_should_replace_connection_low_health_score() -> None:
    """Test connection marked for replacement with low health score."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        min_health_threshold=0.5,
        unhealthy_grace_period=2,
    )
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    # Initialize with poor health
    swarm.initialize_connection_health(peer_id, conn)
    health = swarm.health_data[peer_id][conn]
    health.health_score = 0.2  # Below threshold
    health.consecutive_unhealthy = 2  # Meet grace period

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    should_replace = monitor._should_replace_connection(peer_id, conn)

    assert should_replace is True


@pytest.mark.trio
async def test_should_replace_connection_high_latency() -> None:
    """Test connection marked for replacement with high latency."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        max_ping_latency=100.0,
        unhealthy_grace_period=1,
    )
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    swarm.initialize_connection_health(peer_id, conn)
    health = swarm.health_data[peer_id][conn]
    health.ping_latency = 500.0  # Very high
    health.consecutive_unhealthy = 1

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    should_replace = monitor._should_replace_connection(peer_id, conn)

    assert should_replace is True


@pytest.mark.trio
async def test_should_replace_connection_low_success_rate() -> None:
    """Test connection marked for replacement with low success rate."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        min_ping_success_rate=0.7,
        unhealthy_grace_period=1,
    )
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    swarm.initialize_connection_health(peer_id, conn)
    health = swarm.health_data[peer_id][conn]
    health.ping_success_rate = 0.3  # Low
    health.consecutive_unhealthy = 1

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    should_replace = monitor._should_replace_connection(peer_id, conn)

    assert should_replace is True


@pytest.mark.trio
async def test_should_replace_connection_too_many_failed_streams() -> None:
    """Test connection marked for replacement with too many failed streams."""
    config = ConnectionConfig(
        enable_health_monitoring=True, max_failed_streams=5, unhealthy_grace_period=1
    )
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    swarm.initialize_connection_health(peer_id, conn)
    health = swarm.health_data[peer_id][conn]
    health.failed_streams = 10  # Too many
    health.consecutive_unhealthy = 1

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    should_replace = monitor._should_replace_connection(peer_id, conn)

    assert should_replace is True


@pytest.mark.trio
async def test_should_replace_connection_grace_period() -> None:
    """Test grace period prevents premature replacement."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        min_health_threshold=0.5,
        unhealthy_grace_period=3,
    )
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    swarm.initialize_connection_health(peer_id, conn)
    health = swarm.health_data[peer_id][conn]
    health.health_score = 0.2  # Unhealthy
    health.consecutive_unhealthy = 0  # Start at 0

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # First check - increments to 1
    should_replace = monitor._should_replace_connection(peer_id, conn)
    assert should_replace is False
    assert health.consecutive_unhealthy == 1

    # Second check - increments to 2
    should_replace = monitor._should_replace_connection(peer_id, conn)
    assert should_replace is False
    assert health.consecutive_unhealthy == 2

    # Third check - increments to 3, meets grace period
    should_replace = monitor._should_replace_connection(peer_id, conn)
    assert should_replace is True
    assert health.consecutive_unhealthy == 0  # Reset after replacement decision


@pytest.mark.trio
async def test_should_replace_connection_with_active_streams() -> None:
    """Test connection not replaced if streams are active."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        min_health_threshold=0.5,
        unhealthy_grace_period=1,
    )
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    # Add active stream
    mock_stream = Mock(spec=INetStream)
    conn.streams.add(mock_stream)

    swarm.initialize_connection_health(peer_id, conn)
    health = swarm.health_data[peer_id][conn]
    health.health_score = 0.1  # Very unhealthy
    health.consecutive_unhealthy = 5

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    should_replace = monitor._should_replace_connection(peer_id, conn)

    # Should not replace with active streams
    assert should_replace is False


@pytest.mark.trio
async def test_replace_unhealthy_connection() -> None:
    """Test unhealthy connection replacement."""
    config = ConnectionConfig(enable_health_monitoring=True, min_connections_per_peer=1)
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    old_conn = MockConnection(peer_id)
    healthy_conn = MockConnection(peer_id)  # Keep a healthy connection

    # Add two connections to swarm (so we can replace one)
    swarm.connections[peer_id] = [old_conn, healthy_conn]
    swarm.initialize_connection_health(peer_id, old_conn)
    swarm.initialize_connection_health(peer_id, healthy_conn)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Replace the unhealthy connection
    await monitor._replace_unhealthy_connection(peer_id, old_conn)

    # Verify cleanup called
    assert swarm.cleanup_connection_health_called == 1

    # Verify old connection removed
    assert old_conn not in swarm.connections.get(peer_id, [])

    # Verify old connection closed
    assert old_conn.close_called

    # Verify dial_peer_replacement called
    assert swarm.dial_peer_replacement_called == 1


@pytest.mark.trio
async def test_replace_unhealthy_connection_respects_minimum() -> None:
    """Test replacement blocked if below min_connections_per_peer."""
    config = ConnectionConfig(enable_health_monitoring=True, min_connections_per_peer=2)
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    # Only one connection (below minimum)
    swarm.connections[peer_id] = [conn]
    swarm.initialize_connection_health(peer_id, conn)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Try to replace
    await monitor._replace_unhealthy_connection(peer_id, conn)

    # Should not have called cleanup (replacement blocked)
    assert swarm.cleanup_connection_health_called == 0
    assert not conn.close_called


@pytest.mark.trio
async def test_replace_unhealthy_connection_dial_failure() -> None:
    """Test replacement handles dial failure gracefully."""
    config = ConnectionConfig(enable_health_monitoring=True, min_connections_per_peer=1)
    swarm = MockSwarm(config)

    # Make dial_peer_replacement raise an exception
    async def failing_dial(peer_id):  # type: ignore[no-untyped-def]
        raise Exception("Dial failed")

    swarm.dial_peer_replacement = failing_dial  # type: ignore[method-assign]

    peer_id = ID(b"peer1")
    old_conn = MockConnection(peer_id)
    healthy_conn = MockConnection(peer_id)  # Keep a healthy connection

    # Add two connections (so we can replace one)
    swarm.connections[peer_id] = [old_conn, healthy_conn]
    swarm.initialize_connection_health(peer_id, old_conn)
    swarm.initialize_connection_health(peer_id, healthy_conn)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Should not raise exception even though dial fails
    await monitor._replace_unhealthy_connection(peer_id, old_conn)

    # Old connection should still be cleaned up and closed
    assert old_conn.close_called


@pytest.mark.trio
async def test_get_monitoring_status_enabled() -> None:
    """Test monitoring status reporting when enabled."""
    config = ConnectionConfig(enable_health_monitoring=True, health_check_interval=30.0)
    swarm = MockSwarm(config)

    # Add some connections
    peer1 = ID(b"peer1")
    peer2 = ID(b"peer2")
    conn1 = MockConnection(peer1)
    conn2 = MockConnection(peer2)

    swarm.connections = {peer1: [conn1], peer2: [conn2]}
    swarm.initialize_connection_health(peer1, conn1)
    swarm.initialize_connection_health(peer2, conn2)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]
    monitor._monitoring_task_started.set()

    status = await monitor.get_monitoring_status()

    assert status.enabled is True
    assert status.monitoring_task_started is True
    assert status.check_interval_seconds == 30.0
    assert status.total_connections == 2
    assert status.monitored_connections == 2
    assert status.total_peers == 2
    assert status.monitored_peers == 2


@pytest.mark.trio
async def test_get_monitoring_status_disabled() -> None:
    """Test monitoring status reporting when disabled."""
    config = ConnectionConfig(enable_health_monitoring=False)
    swarm = MockSwarm(config)
    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    status = await monitor.get_monitoring_status()

    assert status.enabled is False
    assert status.monitoring_task_started is False


@pytest.mark.trio
async def test_has_health_data() -> None:
    """Test _has_health_data helper method."""
    config = ConnectionConfig(enable_health_monitoring=True)
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # No health data yet
    assert monitor._has_health_data(peer_id, conn) is False

    # Initialize health data
    swarm.initialize_connection_health(peer_id, conn)

    # Now has health data
    assert monitor._has_health_data(peer_id, conn) is True


@pytest.mark.trio
async def test_health_check_updates_metrics() -> None:
    """Test health check updates connection metrics correctly."""
    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_warmup_window=0.0,  # Disable warmup for test
        ping_timeout=1.0,
    )
    swarm = MockSwarm(config)
    peer_id = ID(b"peer1")
    conn = MockConnection(peer_id)

    swarm.connections[peer_id] = [conn]
    swarm.initialize_connection_health(peer_id, conn)

    monitor = ConnectionHealthMonitor(swarm)  # type: ignore[arg-type]

    # Get initial health state
    health = swarm.health_data[peer_id][conn]
    initial_last_ping = health.last_ping

    # Small delay to ensure timestamp changes
    await trio.sleep(0.01)

    # Perform health check
    await monitor._check_connection_health(peer_id, conn)

    # Verify metrics updated
    assert health.last_ping > initial_last_ping
    assert health.ping_latency >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
